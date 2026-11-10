/* SPDX-License-Identifier: GPL-2.0
 * Optional arm64 device probe, not a KPM/module payload. Requires existing root.
 * Queries the pinned SUSFS ABI, briefly changes uname's reported release, and
 * restores the original release/version before evaluating the result. No disk
 * configuration, modules, grants, partitions or SELinux settings are changed.
 *
 * Build with aarch64-none-elf-gcc -Os -Wall -Werror -ffreestanding -nostdlib
 * -fno-builtin -fno-stack-protector -Wl,-e,_start -o susfs-probe this-file.c
 *
 * SUSFS multiplexes queries over reboot(142), using NON-reboot magic values.
 * The kernel hook writes the response then normal reboot validation rejects
 * these magic values with EINVAL. Never substitute Linux reboot magic here.
 */
#if !defined(__aarch64__)
#error This probe requires arm64 Linux.
#endif

typedef unsigned long usize;
struct uts { char sysname[65], nodename[65], release[65], version[65], machine[65], domain[65]; };
struct text16 { char value[16]; int err; };
struct features { char value[8192]; int err; };
struct uname_request { char release[65], version[65]; int err; };

static long call4(long nr, long a, long b, long c, long d)
{
    register long x0 __asm__("x0") = a;
    register long x1 __asm__("x1") = b;
    register long x2 __asm__("x2") = c;
    register long x3 __asm__("x3") = d;
    register long x8 __asm__("x8") = nr;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x8) : "memory", "cc");
    return x0;
}

static usize length(const char *s, usize cap)
{
    usize n = 0;
    while (n < cap && s[n]) ++n;
    return n;
}

static void print(const char *s, usize cap)
{
    usize n = length(s, cap);
    while (n) {
        long written = call4(64, 1, (long)s, n, 0);
        if (written <= 0) return;
        s += written; n -= written;
    }
}
#define SAY(s) print(s, sizeof(s) - 1)

static void copy65(char *to, const char *from)
{
    usize i;
    for (i = 0; i < 65; ++i) to[i] = from[i];
}

static int equal65(const char *a, const char *b)
{
    usize i;
    for (i = 0; i < 65; ++i) {
        if (a[i] != b[i]) return 0;
        if (!a[i]) return 1;
    }
    return 0;
}

static void query(long command, void *response)
{
    (void)call4(142, 0xDEADBEEFUL, 0xFAFAFAFAUL, command, (long)response);
}

__attribute__((used)) static long probe_main(void)
{
    static struct text16 version = {.err = -12345}, variant = {.err = -12345};
    static struct features features = {.err = -12345};
    static struct uts before, during, after;
    static struct uname_request restore, test = {.release = "ksu-susfs-selftest", .err = -12345};
    long during_rc, after_rc;
    if (call4(174, 0, 0, 0, 0) != 0) { SAY("FAIL: requires root\n"); return 1; }
    query(0x555e1, &version);
    query(0x555e3, &variant);
    query(0x555e2, &features);
    if (version.err || variant.err || features.err || !version.value[0] ||
        length(version.value, 16) == 16 || length(variant.value, 16) == 16 ||
        length(features.value, 8192) == 8192) {
        SAY("FAIL: SUSFS query ABI; no mutation attempted\n"); return 2;
    }
    SAY("version="); print(version.value, 16); SAY("\nvariant="); print(variant.value, 16);
    SAY("\nfeatures="); print(features.value, 8192); SAY("\n");
    if (call4(160, (long)&before, 0, 0, 0)) { SAY("FAIL: uname baseline\n"); return 3; }
    copy65(restore.release, before.release); copy65(restore.version, before.version);
    copy65(test.version, before.version);
    query(0x55590, &test);
    during_rc = call4(160, (long)&during, 0, 0, 0);
    /* Always restore before any printing or result-dependent return. */
    query(0x55590, &restore);
    after_rc = call4(160, (long)&after, 0, 0, 0);
    if (after_rc || !equal65(before.release, after.release) || !equal65(before.version, after.version)) {
        SAY("FAIL: uname restoration; reboot clears temporary kernel state\n"); return 4;
    }
    if (during_rc || !equal65(during.release, test.release) || !equal65(during.version, before.version)) {
        SAY("FAIL: uname did not change; original restored\n"); return 5;
    }
    SAY("PASS: real uname change observed and original restored; no persistent config written\n");
    return 0;
}

__asm__(".text\n.global _start\n_start:\nbl probe_main\nmov x8, #93\nsvc #0\nb .\n");
