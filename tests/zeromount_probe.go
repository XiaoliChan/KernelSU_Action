// Standalone Android/Linux ARM64 diagnostic for the experimental core only.
// Build: GOTOOLCHAIN=local CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -o zm-probe tests/zeromount_probe.go
// Run as root: ./zm-probe smoke /data/local/tmp
package main

import (
	"bytes"
	"crypto/sha256"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"syscall"
	"unsafe"
)

const magic = 0x5a
const version = 0x04190001
const testUID = 65534

func ioc(dir, n, size uintptr) uintptr { return dir<<30 | size<<16 | magic<<8 | n }

//go:uintptrescapes
func call(fd, cmd, arg uintptr) (uintptr, error) {
	r, _, e := syscall.Syscall(syscall.SYS_IOCTL, fd, cmd, arg)
	if e != 0 {
		return r, e
	}
	return r, nil
}

type ruleRequest struct {
	Virtual, Real uintptr
	Flags         uint32
}

func rule(fd uintptr, n uintptr, v, r string) error {
	vb, rb := append([]byte(v), 0), append([]byte(r), 0)
	data := ruleRequest{Virtual: uintptr(unsafe.Pointer(&vb[0])), Real: uintptr(unsafe.Pointer(&rb[0]))}
	_, err := call(fd, ioc(1, n, unsafe.Sizeof(data)), uintptr(unsafe.Pointer(&data)))
	runtime.KeepAlive(vb)
	runtime.KeepAlive(rb)
	runtime.KeepAlive(data)
	return err
}
func uidRule(fd uintptr, n uintptr) error {
	uid := uint32(testUID)
	_, err := call(fd, ioc(1, n, 4), uintptr(unsafe.Pointer(&uid)))
	runtime.KeepAlive(uid)
	return err
}
func worker(path string) error {
	if err := syscall.Setgroups(nil); err != nil {
		return err
	}
	if err := syscall.Setgid(testUID); err != nil {
		return err
	}
	if err := syscall.Setuid(testUID); err != nil {
		return err
	}
	// The root-opened control FD is inherited as 3. Passing an FD must not
	// bypass ioctl authorization after the caller loses its privileges.
	if _, err := call(3, ioc(0, 8, 0), 0); !errors.Is(err, syscall.EPERM) {
		return fmt.Errorf("nonroot control not denied: %v", err)
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	fmt.Printf("%x\n", sha256.Sum256(b))
	return nil
}
func checkWorker(exe, path string, fd *os.File, want []byte) error {
	cmd := exec.Command(exe, "worker", path)
	cmd.ExtraFiles = []*os.File{fd}
	b, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("worker: %w (%s)", err, b)
	}
	expected := []byte(fmt.Sprintf("%x\n", sha256.Sum256(want)))
	if !bytes.Equal(b, expected) {
		return fmt.Errorf("worker digest mismatch: got %s", b)
	}
	return nil
}
func smoke(parent string) (err error) {
	if os.Geteuid() != 0 {
		return errors.New("root required")
	}
	if runtime.GOARCH != "arm64" && runtime.GOARCH != "arm" {
		return errors.New("Android ARM/ARM64 diagnostic only")
	}
	f, err := os.OpenFile("/dev/zeromount", os.O_RDWR, 0)
	if err != nil {
		return err
	}
	defer f.Close()
	fd := f.Fd()
	v, err := call(fd, ioc(2, 4, 4), 0)
	if err != nil {
		return err
	}
	if v != version {
		return fmt.Errorf("wrong experimental ABI: %#x", v)
	}
	state, err := call(fd, ioc(2, 11, 4), 0)
	if err != nil {
		return err
	}
	if state != 0 {
		return errors.New("refusing to alter active existing rules")
	}
	buf := make([]byte, 64*1024)
	n, err := call(fd, ioc(2, 7, 4), uintptr(unsafe.Pointer(&buf[0])))
	runtime.KeepAlive(buf)
	if err != nil {
		return err
	}
	if n != 0 {
		return errors.New("refusing to alter pre-existing rules")
	}
	dir, err := os.MkdirTemp(parent, "zeromount-core-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(dir)
	if err = os.Chmod(dir, 0755); err != nil {
		return err
	}
	virtual, real := filepath.Join(dir, "virtual"), filepath.Join(dir, "replacement")
	base, data := []byte("ZEROMOUNT_BASELINE\n"), []byte("ZEROMOUNT_REPLACEMENT\n")
	for p, b := range map[string][]byte{virtual: base, real: data} {
		if err = os.WriteFile(p, b, 0644); err != nil {
			return err
		}
		if err = os.Chmod(p, 0644); err != nil {
			return err
		}
	}
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	if err = checkWorker(exe, virtual, f, base); err != nil {
		return fmt.Errorf("baseline access (do not disable SELinux to force a pass): %w", err)
	}
	added, blocked := false, false
	defer func() {
		_, e := call(fd, ioc(0, 9, 0), 0)
		err = errors.Join(err, e)
		if blocked {
			err = errors.Join(err, uidRule(fd, 6))
		}
		if added {
			err = errors.Join(err, rule(fd, 2, virtual, real))
		}
	}()
	if err = rule(fd, 1, virtual, real); err != nil {
		return err
	}
	added = true
	if _, err = call(fd, ioc(0, 8, 0), 0); err != nil {
		return err
	}
	if err = checkWorker(exe, virtual, f, data); err != nil {
		return err
	}
	if b, e := os.ReadFile(virtual); e != nil || !bytes.Equal(b, base) {
		return errors.New("root view changed unexpectedly")
	}
	if e := rule(fd, 1, virtual, real); !errors.Is(e, syscall.EBUSY) {
		return fmt.Errorf("active mutation not denied: %v", e)
	}
	if _, err = call(fd, ioc(0, 9, 0), 0); err != nil {
		return err
	}
	if err = checkWorker(exe, virtual, f, base); err != nil {
		return err
	}
	if err = uidRule(fd, 5); err != nil {
		return err
	}
	blocked = true
	if _, err = call(fd, ioc(0, 8, 0), 0); err != nil {
		return err
	}
	if err = checkWorker(exe, virtual, f, base); err != nil {
		return err
	}
	return nil
}
func main() {
	var err error
	if len(os.Args) != 3 {
		err = errors.New("usage: zm-probe smoke <test-parent> | worker <test-file>")
	} else if os.Args[1] == "worker" {
		err = worker(os.Args[2])
	} else if os.Args[1] == "smoke" {
		err = smoke(os.Args[2])
	} else {
		err = errors.New("unknown command")
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if os.Args[1] == "smoke" {
		fmt.Println("PASS: absolute redirect, root exclusion, nonroot ioctl denial, disable restore, UID exclusion, active mutation denial, cleanup")
	}
}
