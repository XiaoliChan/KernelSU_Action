/*
 * Experimental 4.19 absolute-file core, derived from Super-Builders c2cb716.
 * Original source and provenance are retained in ../upstream and the lock file.
 * Deliberately no DAC/SELinux bypass, directory injection or metadata spoofing.
 */
#include <linux/module.h>
#include <linux/init.h>
#include <linux/fs.h>
#include <linux/namei.h>
#include <linux/cred.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/uaccess.h>
#include <linux/compat.h>
#include <linux/miscdevice.h>
#include <linux/mutex.h>
#include <linux/hashtable.h>
#include <linux/rcupdate.h>
#include <linux/reboot.h>
#include <linux/susfs_def.h>
#include <linux/zeromount.h>

struct zm_rule {
	struct hlist_node node;
	struct list_head list;
	struct rcu_head rcu;
	char *virtual_path;
	char *real_path;
};
struct zm_uid {
	struct hlist_node node;
	struct rcu_head rcu;
	uid_t uid;
};
static DEFINE_HASHTABLE(zm_rules, 10);
static DEFINE_HASHTABLE(zm_blocked_uids, 8);
static LIST_HEAD(zm_rule_list);
static DEFINE_MUTEX(zm_control_lock);
static atomic_t zm_enabled = ATOMIC_INIT(0);
static unsigned int zm_count;
static unsigned int zm_uid_count;
#define ZM_MAX_RULES 256
#define ZM_LIST_SIZE (64 * 1024)

static bool zm_app_allowed(void)
{
	extern bool __ksu_is_allow_uid_for_current(uid_t uid);
	uid_t uid = current_uid().val;
	if (!atomic_read(&zm_enabled) || zm_is_recursive())
		return false;
	if ((uid % 100000) < 10000 || !current->mm || current->journal_info ||
	    (current->flags & (PF_KTHREAD | PF_EXITING)))
		return false;
	if (susfs_is_current_proc_umounted())
		return false;
	return !__ksu_is_allow_uid_for_current(uid);
}

/* Exact lexical paths only: never collapse /system/foo into /foo. */
static bool zm_valid_path(const char *path)
{
	size_t len;
	if (!path || path[0] != '/')
		return false;
	len = strlen(path);
	if (len < 2 || len >= PATH_MAX || path[len - 1] == '/' ||
	    strstr(path, "//") || strstr(path, "/./") || strstr(path, "/../") ||
	    !strcmp(path + len - 2, "/.") ||
	    (len >= 3 && !strcmp(path + len - 3, "/..")))
		return false;
	return true;
}

static int zm_validate_file(const char *name)
{
	struct path path;
	struct inode *inode;
	int ret;
	if (!zm_valid_path(name))
		return -EINVAL;
	/* No LOOKUP_FOLLOW: final symlinks are unsupported in this stage. */
	ret = kern_path(name, 0, &path);
	if (ret)
		return ret;
	inode = d_backing_inode(path.dentry);
	ret = (!inode || !S_ISREG(inode->i_mode) ||
	       !uid_eq(inode->i_uid, GLOBAL_ROOT_UID) ||
	       !(inode->i_mode & S_IROTH) ||
	       (inode->i_mode & (S_IWGRP | S_IWOTH))) ? -EACCES : 0;
	path_put(&path);
	return ret;
}

struct filename *zeromount_getname_hook(struct filename *name)
{
	struct zm_rule *rule;
	struct zm_uid *uid_entry;
	struct filename *replacement;
	char *target = NULL;
	bool found = false;
	uid_t uid;
	u32 hash;
	if (!zm_app_allowed() || IS_ERR_OR_NULL(name) || !zm_valid_path(name->name))
		return name;
	uid = current_uid().val;
	hash = full_name_hash(NULL, name->name, strlen(name->name));
	/* The RCU hash table is authoritative; no racy Bloom early reject. */
	rcu_read_lock();
	if (!atomic_read(&zm_enabled)) {
		rcu_read_unlock();
		return name;
	}
	hash_for_each_possible_rcu(zm_blocked_uids, uid_entry, node, uid) {
		if (uid_entry->uid == uid) {
			rcu_read_unlock();
			return name;
		}
	}
	hash_for_each_possible_rcu(zm_rules, rule, node, hash) {
		if (!strcmp(rule->virtual_path, name->name)) {
			found = true;
			target = kstrdup(rule->real_path, GFP_ATOMIC);
			break;
		}
	}
	rcu_read_unlock();
	if (!found)
		return name;
	/* Never silently read the original file after a matched allocation failure. */
	if (!target) {
		putname(name);
		return ERR_PTR(-ENOMEM);
	}
	zm_enter();
	replacement = getname_kernel(target);
	zm_exit();
	kfree(target);
	putname(name);
	return replacement;
}

static void zm_free_rule(struct rcu_head *head)
{
	struct zm_rule *rule = container_of(head, struct zm_rule, rcu);
	kfree(rule->virtual_path);
	kfree(rule->real_path);
	kfree(rule);
}

static int zm_copy_request(struct zeromount_ioctl_data *data, unsigned long arg)
{
#ifdef CONFIG_COMPAT
	if (in_compat_syscall()) {
		struct zeromount_compat_data compat;
		if (copy_from_user(&compat, compat_ptr(arg), sizeof(compat)))
			return -EFAULT;
		data->virtual_path = compat_ptr(compat.virtual_path);
		data->real_path = compat_ptr(compat.real_path);
		data->flags = compat.flags;
		return 0;
	}
#endif
	return copy_from_user(data, (void __user *)arg, sizeof(*data)) ? -EFAULT : 0;
}

/* Writers hold zm_control_lock; changes are accepted only while disabled. */
static int zm_rule_change(unsigned long arg, bool add)
{
	struct zeromount_ioctl_data data;
	struct zm_rule *rule;
	char *vpath, *rpath = NULL;
	u32 hash;
	int ret = zm_copy_request(&data, arg);
	if (ret)
		return ret;
	if (data.flags & ~ZM_FLAG_ACTIVE)
		return -EOPNOTSUPP;
	vpath = strndup_user(data.virtual_path, PATH_MAX);
	if (IS_ERR(vpath))
		return PTR_ERR(vpath);
	if (!zm_valid_path(vpath)) { ret = -EINVAL; goto out; }
	hash = full_name_hash(NULL, vpath, strlen(vpath));
	hash_for_each_possible(zm_rules, rule, node, hash) {
		if (strcmp(rule->virtual_path, vpath))
			continue;
		if (add) { ret = -EEXIST; goto out; }
		hash_del_rcu(&rule->node);
		list_del(&rule->list);
		zm_count--;
		call_rcu(&rule->rcu, zm_free_rule);
		ret = 0;
		goto out;
	}
	if (!add) { ret = -ENOENT; goto out; }
	if (zm_count >= ZM_MAX_RULES) { ret = -ENOSPC; goto out; }
	rpath = strndup_user(data.real_path, PATH_MAX);
	if (IS_ERR(rpath)) { ret = PTR_ERR(rpath); rpath = NULL; goto out; }
	ret = zm_validate_file(vpath);
	if (ret) goto out;
	ret = zm_validate_file(rpath);
	if (ret) goto out;
	if (!strcmp(vpath, rpath)) { ret = -EINVAL; goto out; }
	rule = kzalloc(sizeof(*rule), GFP_KERNEL);
	if (!rule) { ret = -ENOMEM; goto out; }
	rule->virtual_path = vpath;
	rule->real_path = rpath;
	list_add_tail(&rule->list, &zm_rule_list);
	hash_add_rcu(zm_rules, &rule->node, hash);
	zm_count++;
	return 0;
out:
	kfree(vpath);
	kfree(rpath);
	return ret;
}

static void zm_clear(void)
{
	struct zm_rule *rule;
	struct zm_uid *uid;
	struct hlist_node *tmp;
	int bucket;
	hash_for_each_safe(zm_rules, bucket, tmp, rule, node) {
		hash_del_rcu(&rule->node);
		list_del(&rule->list);
		call_rcu(&rule->rcu, zm_free_rule);
	}
	hash_for_each_safe(zm_blocked_uids, bucket, tmp, uid, node) {
		hash_del_rcu(&uid->node);
		kfree_rcu(uid, rcu);
	}
	zm_count = 0;
	zm_uid_count = 0;
}

static int zm_uid_change(unsigned long arg, bool add)
{
	struct zm_uid *entry;
	uid_t uid;
	if (copy_from_user(&uid, (void __user *)arg, sizeof(uid)))
		return -EFAULT;
	hash_for_each_possible(zm_blocked_uids, entry, node, uid) {
		if (entry->uid != uid) continue;
		if (add) return -EEXIST;
		hash_del_rcu(&entry->node);
		zm_uid_count--;
		kfree_rcu(entry, rcu);
		return 0;
	}
	if (!add) return -ENOENT;
	if (zm_uid_count >= ZM_MAX_RULES) return -ENOSPC;
	entry = kmalloc(sizeof(*entry), GFP_KERNEL);
	if (!entry) return -ENOMEM;
	entry->uid = uid;
	hash_add_rcu(zm_blocked_uids, &entry->node, uid);
	zm_uid_count++;
	return 0;
}

static int zm_list(unsigned long arg)
{
	struct zm_rule *rule;
	char *buf = kzalloc(ZM_LIST_SIZE, GFP_KERNEL);
	size_t len = 0, need;
	int ret;
	if (!buf) return -ENOMEM;
	list_for_each_entry(rule, &zm_rule_list, list) {
		need = strlen(rule->real_path) + strlen(rule->virtual_path) + 3;
		if (len + need >= ZM_LIST_SIZE) { kfree(buf); return -ENOBUFS; }
		len += scnprintf(buf + len, ZM_LIST_SIZE - len, "%s->%s\n",
				 rule->real_path, rule->virtual_path);
	}
	ret = copy_to_user((void __user *)arg, buf, len) ? -EFAULT : (int)len;
	kfree(buf);
	return ret;
}

static long zm_ioctl_locked(unsigned int cmd, unsigned long arg)
{
	if (_IOC_TYPE(cmd) != ZEROMOUNT_MAGIC_CODE) return -ENOTTY;
	if (!uid_eq(current_euid(), GLOBAL_ROOT_UID) || !capable(CAP_SYS_ADMIN))
		return -EPERM;
	switch (cmd) {
	case ZEROMOUNT_IOC_GET_VERSION: return ZEROMOUNT_VERSION;
	case ZEROMOUNT_IOC_GET_STATUS: return atomic_read(&zm_enabled);
	case ZEROMOUNT_IOC_GET_LIST: return zm_list(arg);
	case ZEROMOUNT_IOC_ENABLE: atomic_set(&zm_enabled, 1); return 0;
	case ZEROMOUNT_IOC_DISABLE:
		atomic_set(&zm_enabled, 0);
		synchronize_rcu();
		return 0;
	}
	if (atomic_read(&zm_enabled)) return -EBUSY;
	switch (cmd) {
	case ZEROMOUNT_IOC_ADD_RULE: return zm_rule_change(arg, true);
	case ZEROMOUNT_IOC_DEL_RULE: return zm_rule_change(arg, false);
	case ZEROMOUNT_IOC_CLEAR_ALL: zm_clear(); return 0;
	case ZEROMOUNT_IOC_ADD_UID: return zm_uid_change(arg, true);
	case ZEROMOUNT_IOC_DEL_UID: return zm_uid_change(arg, false);
	case ZEROMOUNT_IOC_REFRESH: return -EOPNOTSUPP;
	default: return -ENOTTY;
	}
}

static long zeromount_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	long ret;
	if (mutex_lock_interruptible(&zm_control_lock)) return -ERESTARTSYS;
	ret = zm_ioctl_locked(cmd, arg);
	mutex_unlock(&zm_control_lock);
	return ret;
}
#ifdef CONFIG_COMPAT
static long zeromount_compat_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	if (cmd == ZEROMOUNT_COMPAT_ADD) cmd = ZEROMOUNT_IOC_ADD_RULE;
	else if (cmd == ZEROMOUNT_COMPAT_DEL) cmd = ZEROMOUNT_IOC_DEL_RULE;
	else if (cmd == ZEROMOUNT_IOC_ADD_RULE || cmd == ZEROMOUNT_IOC_DEL_RULE)
		return -EINVAL;
	return zeromount_ioctl(file, cmd, (unsigned long)compat_ptr(arg));
}
#endif
static int zeromount_open(struct inode *inode, struct file *file)
{
	return (uid_eq(current_euid(), GLOBAL_ROOT_UID) && capable(CAP_SYS_ADMIN)) ? 0 : -EPERM;
}
static const struct file_operations zeromount_fops = {
	.owner = THIS_MODULE, .open = zeromount_open, .unlocked_ioctl = zeromount_ioctl,
#ifdef CONFIG_COMPAT
	.compat_ioctl = zeromount_compat_ioctl,
#endif
};
static struct miscdevice zeromount_dev = {
	.minor = MISC_DYNAMIC_MINOR, .name = "zeromount", .fops = &zeromount_fops, .mode = 0600,
};
static int zm_reboot(struct notifier_block *nb, unsigned long action, void *data)
{
	atomic_set(&zm_enabled, 0);
	synchronize_rcu();
	return NOTIFY_OK;
}
static struct notifier_block zm_reboot_nb = { .notifier_call = zm_reboot };
static int __init zeromount_init(void)
{
	int ret = register_reboot_notifier(&zm_reboot_nb);
	if (ret) return ret;
	ret = misc_register(&zeromount_dev);
	if (ret) unregister_reboot_notifier(&zm_reboot_nb);
	return ret;
}
late_initcall(zeromount_init);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Experimental 4.19 absolute-file ZeroMount core");
