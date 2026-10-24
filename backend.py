import os
import re
import subprocess
import sys
import time

BLOCK = 32 * 1024 * 1024
IS_WIN = os.name == "nt"


def disk_size(path):
    if IS_WIN:
        m = re.search(r"PhysicalDrive(\d+)", path, re.I)
        if not m:
            return None
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-Disk -Number {m.group(1)}).Size"], text=True)
            return int(out.strip())
        except Exception:
            return None
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            return os.lseek(fd, 0, os.SEEK_END)
        finally:
            os.close(fd)
    except OSError:
        return None


def is_system_disk(path):
    if IS_WIN:
        m = re.search(r"PhysicalDrive(\d+)", path, re.I)
        if not m:
            return False
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-Disk -Number {m.group(1)}).IsSystem -or "
                 f"(Get-Disk -Number {m.group(1)}).IsBoot"], text=True)
            return out.strip().lower() == "true"
        except Exception:
            return False
    if sys.platform.startswith("linux"):
        real = os.path.realpath(path)
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    dev, mnt = line.split()[:2]
                    if dev.startswith(real) and mnt in ("/", "/boot", "/boot/efi", "/home"):
                        return True
        except OSError:
            pass
    return False


def fmt(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


class WipeError(Exception):
    pass


def windows_clean_partitions(path, log=print):
    if not IS_WIN:
        return
    m = re.search(r"PhysicalDrive(\d+)", path, re.I)
    if not m:
        return
    log("Removing partitions with diskpart...")
    script = f"select disk {m.group(1)}\nclean\n"
    r = subprocess.run(["diskpart"], input=script, text=True,
                        capture_output=True)
    log(r.stdout.strip())
    if r.returncode != 0:
        raise WipeError("diskpart failed. Run as Administrator.")


def wipe(path, progress=None, should_stop=None):
    size = disk_size(path)

    zeros = bytes(BLOCK)
    flags = os.O_WRONLY | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as e:
        raise WipeError(f"Could not open {path} for writing: {e}")

    written = 0
    start = time.time()
    try:
        while True:
            if should_stop is not None and should_stop():
                break
            try:
                n = os.write(fd, zeros)
            except OSError as e:
                if size and written < size - 4 * BLOCK:
                    raise WipeError(f"Write failed at {fmt(written)}: {e}")
                break  # reached end of device
            if n == 0:
                break
            written += n
            if size and written >= size:
                break
            if progress is not None:
                el = max(time.time() - start, 0.001)
                progress(written, size, written / el)
        os.fsync(fd)
    finally:
        os.close(fd)

    return written


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    path = sys.argv[1]

    if not IS_WIN and os.geteuid() != 0:
        sys.exit("Run this as root (sudo).")

    if is_system_disk(path):
        sys.exit(f"Refusing: {path} looks like your system/boot disk.")

    size = disk_size(path)
    print(f"Target : {path}")
    print(f"Size   : {fmt(size) if size else 'unknown'}")
    print("\nALL DATA ON THIS DISK WILL BE PERMANENTLY DESTROYED.")
    if input("Type the exact disk path to confirm: ").strip() != path:
        sys.exit("Confirmation did not match. Aborted.")

    start = time.time()
    try:
        windows_clean_partitions(path)

        def report(written, total, rate):
            pct = f"{written / total * 100:5.1f}%" if total else ""
            print(f"\r{fmt(written)} written  {pct}  {fmt(rate)}/s   ",
                  end="", flush=True)

        written = wipe(path, progress=report)
    except WipeError as e:
        sys.exit(str(e))

    print(f"\nDone. {fmt(written)} zeroed in {time.time() - start:.0f}s.")


if __name__ == "__main__":
    main()