import base64
import dataclasses
import glob
import json
import multiprocessing
import os
import platform
import re
import signal
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from shlex import quote
from threading import Thread
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional, Type, TypeVar, Union

T = TypeVar("T", bound="Serializable")


class MetaClasses:
    class WithIter(type):
        def __iter__(cls):
            return (v for k, v in cls.__dict__.items() if not k.startswith("_"))

    @dataclasses.dataclass
    class Serializable(ABC):
        @classmethod
        def to_dict(cls, obj):
            if dataclasses.is_dataclass(obj):
                return {k: cls.to_dict(v) for k, v in dataclasses.asdict(obj).items()}
            elif isinstance(obj, SimpleNamespace):
                return {k: cls.to_dict(v) for k, v in vars(obj).items()}
            elif isinstance(obj, list):
                return [cls.to_dict(i) for i in obj]
            elif isinstance(obj, dict):
                return {k: cls.to_dict(v) for k, v in obj.items()}
            else:
                return obj

        @classmethod
        def from_dict(cls: Type[T], obj: Dict[str, Any]) -> T:
            return cls(**obj)

        @classmethod
        def from_fs(cls: Type[T], name) -> T:
            with open(cls.file_name_static(name), "r", encoding="utf8") as f:
                try:
                    return cls.from_dict(json.load(f))
                except json.decoder.JSONDecodeError as ex:
                    print(f"ERROR: failed to parse json, ex [{ex}]")
                    print(f"JSON content [{cls.file_name_static(name)}]")
                    Shell.check(f"cat {cls.file_name_static(name)}")
                    raise ex

        @classmethod
        @abstractmethod
        def file_name_static(cls, name):
            pass

        def file_name(self):
            return self.file_name_static(self.name)

        def dump(self):
            with open(self.file_name(), "w", encoding="utf8") as f:
                json.dump(self.to_dict(self), f, indent=4)
            return self

        @classmethod
        def exist(cls, name):
            return Path(cls.file_name_static(name)).is_file()

        def to_json(self, pretty=False):
            return json.dumps(dataclasses.asdict(self), indent=4 if pretty else None)

    @dataclasses.dataclass
    class SerializableSingleton(ABC):
        @classmethod
        def to_dict(cls, obj):
            if dataclasses.is_dataclass(obj):
                return {k: cls.to_dict(v) for k, v in dataclasses.asdict(obj).items()}
            elif isinstance(obj, SimpleNamespace):
                return {k: cls.to_dict(v) for k, v in vars(obj).items()}
            elif isinstance(obj, list):
                return [cls.to_dict(i) for i in obj]
            elif isinstance(obj, dict):
                return {k: cls.to_dict(v) for k, v in obj.items()}
            else:
                return obj

        @classmethod
        def from_dict(cls: Type[T], obj: Dict[str, Any]) -> T:
            return cls(**obj)

        @classmethod
        @abstractmethod
        def file_name_static(cls):
            pass

        @classmethod
        def from_fs(cls: Type[T]) -> T:
            with open(cls.file_name_static(), "r", encoding="utf8") as f:
                try:
                    return cls.from_dict(json.load(f))
                except json.decoder.JSONDecodeError as ex:
                    print(f"ERROR: failed to parse json, ex [{ex}]")
                    print(f"JSON content [{cls.file_name_static()}]")
                    Shell.check(f"cat {cls.file_name_static()}")
                    raise ex

        def dump(self):
            with open(self.file_name_static(), "w", encoding="utf8") as f:
                json.dump(self.to_dict(self), f, indent=4)
            return self

        @classmethod
        def exist(cls):
            return Path(cls.file_name_static()).is_file()

        def to_json(self, pretty=False):
            return json.dumps(dataclasses.asdict(self), indent=4 if pretty else None)


class ContextManager:
    @staticmethod
    @contextmanager
    def cd(to: Optional[Union[Path, str]]) -> Iterator[None]:
        """
        changes current working directory to @path or `git root` if @path is None
        :param to:
        :return:
        """
        # if not to:
        #     try:
        #         to = Shell.get_output_or_raise("git rev-parse --show-toplevel")
        #     except:
        #         pass
        #     if not to:
        #         if Path(_Settings.DOCKER_WD).is_dir():
        #             to = _Settings.DOCKER_WD
        #     if not to:
        #         assert False, "FIX IT"
        #     assert to
        old_pwd = os.getcwd()
        if to:
            os.chdir(to)
        try:
            yield
        finally:
            os.chdir(old_pwd)


class Shell:
    @classmethod
    def get_output_or_raise(cls, command, verbose=False):
        return cls.get_output(command, verbose=verbose, strict=True).strip()

    @classmethod
    def get_output(cls, command, strict=False, verbose=False):
        if verbose:
            print(f"Run command [{command}]")
        res = subprocess.run(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            executable="/bin/bash",
            errors="ignore",
        )
        if res.stderr:
            print(f"WARNING: stderr: {res.stderr.strip()}")
        if strict and res.returncode != 0:
            raise RuntimeError(
                f"command failed with, exit_code {res.returncode}, stderr:\n>>>\n{res.stderr.strip()}\n<<<"
            )
        return res.stdout.strip()

    @classmethod
    def get_res_stdout_stderr(cls, command, verbose=True, strip=True):
        if verbose:
            print(f"Run command [{command}]")
        res = subprocess.run(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="ignore",
        )
        if strip:
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        else:
            return res.returncode, res.stdout, res.stderr

    @classmethod
    def check(
        cls,
        command,
        log_file=None,
        strict=False,
        verbose=False,
        dry_run=False,
        stdin_str=None,
        timeout=None,
        retries=1,
        **kwargs,
    ):
        return (
            cls.run(
                command,
                log_file,
                strict,
                verbose,
                dry_run,
                stdin_str,
                retries=retries,
                timeout=timeout,
                **kwargs,
            )
            == 0
        )

    @classmethod
    def check_parallel(
        cls,
        commands,
        verbose=False,
        max_workers=None,
    ):
        if verbose:
            print(
                f"Run in parallel: [{len(commands)}], workers [{max_workers or len(commands)}]"
            )

        def execute(command):
            return cls.get_res_stdout_stderr(command, verbose=True)

        with ThreadPoolExecutor(max_workers=max_workers or len(commands)) as executor:
            futures = {
                executor.submit(execute, command): command for command in commands
            }
            results = []
            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                except Exception:
                    results.append(False)
        failed = False
        for res, out_, err in results:
            if res != 0:
                print(f"Check Parallel failed, err: [{(res, out_, err)}]")
                failed = True
        return not failed

    @classmethod
    def _check_timeout(cls, timeout, process) -> None:
        if not timeout:
            return
        time.sleep(timeout)
        print(
            f"WARNING: Timeout exceeded [{timeout}], sending SIGTERM to process group [{process.pid}]"
        )
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            print("Process already terminated.")
            return

        time_wait = 0
        wait_interval = 5

        # Wait for process to terminate
        while process.poll() is None and time_wait < 100:
            print("Waiting for process to exit...")
            time.sleep(wait_interval)
            time_wait += wait_interval

        # Force kill if still running
        if process.poll() is None:
            print(f"WARNING: Process still running after SIGTERM, sending SIGKILL")
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                print("Process already terminated.")

    @classmethod
    def run(
        cls,
        command,
        log_file=None,
        strict=False,
        verbose=False,
        dry_run=False,
        stdin_str=None,
        timeout=None,
        retries=1,
        **kwargs,
    ):
        # Dry-run
        if dry_run:
            print(f"Dry-run. Would run command [{command}]")
            return 0  # Return success for dry-run

        if verbose:
            print(f"Run command: [{command}]")

        log_file = log_file or "/dev/null"
        proc = None
        err_output = []
        for retry in range(retries):
            try:
                with open(log_file, "w") as log_fp:
                    proc = subprocess.Popen(
                        command,
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        stdin=subprocess.PIPE if stdin_str else None,
                        universal_newlines=True,
                        start_new_session=True,  # Start a new process group for signal handling
                        bufsize=1,  # Line-buffered
                        errors="backslashreplace",
                        executable="/bin/bash",
                        **kwargs,
                    )

                    # Start the timeout thread if specified
                    if timeout:
                        t = Thread(target=cls._check_timeout, args=(timeout, proc))
                        t.daemon = True
                        t.start()

                    # Write stdin if provided
                    if stdin_str:
                        proc.stdin.write(stdin_str)
                        proc.stdin.close()

                    # Process both stdout and stderr in real-time
                    def stream_output(stream, output_fp, output=None):
                        for line in iter(stream.readline, ""):
                            sys.stdout.write(line)
                            output_fp.write(line)
                            if output is not None:
                                output.append(line)

                    err_output = []
                    stdout_thread = Thread(
                        target=stream_output, args=(proc.stdout, log_fp, None)
                    )
                    stderr_thread = Thread(
                        target=stream_output, args=(proc.stderr, log_fp, err_output)
                    )

                    stdout_thread.start()
                    stderr_thread.start()

                    stdout_thread.join()
                    stderr_thread.join()

                    proc.wait()  # Wait for the process to finish

                    if proc.returncode == 0:
                        break  # Exit retry loop if success
                    else:
                        if verbose:
                            print(
                                f"ERROR: command failed, exit code: {proc.returncode}, retry: {retry}/{retries}"
                            )
            except Exception as e:
                if verbose:
                    print(
                        f"ERROR: command failed, exception: {e}, retry: {retry}/{retries}"
                    )
                if proc:
                    proc.kill()
                if strict and retry == retries - 1:
                    raise e

            if strict and (not proc or proc.returncode != 0):
                err = "\n   ".join(err_output).strip()
                raise RuntimeError(
                    f"command failed, exit code {proc.returncode},\nstderr:\n>>>\n{err}\n<<<"
                )

        return proc.returncode if proc else 1  # Return 1 if the process never started

    @classmethod
    def run_async(
        cls,
        command,
        stdin_str=None,
        verbose=False,
        suppress_output=False,
        **kwargs,
    ):
        if verbose:
            print(f"Run command in background [{command}]")
        proc = subprocess.Popen(
            command,
            shell=True,
            stderr=subprocess.STDOUT if not suppress_output else subprocess.DEVNULL,
            stdout=subprocess.PIPE if not suppress_output else subprocess.DEVNULL,
            stdin=subprocess.PIPE if stdin_str else None,
            universal_newlines=True,
            start_new_session=True,
            bufsize=1,
            errors="backslashreplace",
            **kwargs,
        )
        if proc.stdout:
            for line in proc.stdout:
                print(line, end="")
        return proc


class Utils:

    @staticmethod
    def absolute_path(path):
        return os.path.abspath(str(path))

    @staticmethod
    def is_arm():
        arch = platform.machine()
        if "arm" in arch.lower() or "aarch" in arch.lower():
            return True
        return False

    @staticmethod
    def is_amd():
        arch = platform.machine()
        if "x86" in arch.lower() or "amd" in arch.lower():
            return True
        return False

    @staticmethod
    def terminate_process_group(pid, force=False):
        try:
            if not force:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            else:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception as e:
            print(
                f"ERROR: Exception while terminating process [{pid}]: [{e}], (force={force})"
            )

    @staticmethod
    def terminate_process(pid, force=False):
        try:
            if not force:
                os.kill(pid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGKILL)
        except Exception as e:
            print(
                f"ERROR: Exception while terminating process [{pid}]: [{e}], (force={force})"
            )

    @staticmethod
    def set_env(key, val):
        os.environ[key] = val

    @staticmethod
    def print_formatted_error(error_message, stdout="", stderr=""):
        stdout_lines = stdout.splitlines() if stdout else []
        stderr_lines = stderr.splitlines() if stderr else []
        print(f"ERROR: {error_message}")
        if stdout_lines:
            print("  Out:")
            for line in stdout_lines:
                print(f"     | {line}")
        if stderr_lines:
            print("  Err:")
            for line in stderr_lines:
                print(f"     | {line}")

    @staticmethod
    def sleep(seconds):
        time.sleep(seconds)

    @staticmethod
    def cwd():
        return str(Path.cwd())

    @staticmethod
    def cpu_count():
        return multiprocessing.cpu_count()

    # deprecated: unnecessary lines in traceback + ide linting issues
    # switch to regular raise Ex() inplace
    @staticmethod
    def raise_with_error(error_message, stdout="", stderr="", ex=None):
        Utils.print_formatted_error(error_message, stdout, stderr)
        raise ex or RuntimeError(error_message)

    @staticmethod
    def timestamp():
        return datetime.now().timestamp()

    @staticmethod
    def timestamp_to_str(timestamp):
        return datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def get_failed_tests_number(description: str) -> Optional[int]:
        description = description.lower()

        pattern = r"fail:\s*(\d+)\s*(?=,|$)"
        match = re.search(pattern, description)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def is_killed_with_oom():
        if Shell.check(
            "sudo dmesg -T | grep -q -e 'Out of memory: Killed process' -e 'oom_reaper: reaped process' -e 'oom-kill:constraint=CONSTRAINT_NONE'"
        ):
            return True
        return False

    @staticmethod
    def clear_dmesg():
        Shell.check("sudo dmesg --clear", verbose=True)

    @staticmethod
    def to_base64(value):
        assert isinstance(value, str), f"TODO: not supported for {type(value)}"
        string_bytes = value.encode("utf-8")
        base64_bytes = base64.b64encode(string_bytes)
        base64_string = base64_bytes.decode("utf-8")
        return base64_string

    @staticmethod
    def is_hex(s):
        try:
            int(s, 16)
            return True
        except ValueError:
            return False

    @staticmethod
    def normalize_string(string: str) -> str:
        res = string.lower()
        for r in (
            (" ", "_"),
            ("(", "_"),
            (")", "_"),
            ("{", "_"),
            ("}", "_"),
            ("'", "_"),
            ("[", "_"),
            ("]", "_"),
            (",", "_"),
            ("/", "_"),
            ("-", "_"),
            (":", "_"),
            ('"', "_"),
            ("&", "_"),
        ):
            res = res.replace(*r)
            res = re.sub(r"_+", "_", res)
            res = res.rstrip("_")
        return res

    @staticmethod
    def traverse_path(path, file_suffixes=None, sorted=False, not_exists_ok=False):
        res = []

        def is_valid_file(file):
            if file_suffixes is None:
                return True
            return any(file.endswith(suffix) for suffix in file_suffixes)

        if os.path.isfile(path):
            if is_valid_file(path):
                res.append(path)
        elif os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for file in files:
                    full_path = os.path.join(root, file)
                    if is_valid_file(full_path):
                        res.append(full_path)
        elif "*" in str(path):
            res.extend(
                [
                    f
                    for f in glob.glob(path, recursive=True)
                    if os.path.isfile(f) and is_valid_file(f)
                ]
            )
        else:
            if not_exists_ok:
                pass
            else:
                assert False, f"File does not exist or not valid [{path}]"

        if sorted:
            res.sort(reverse=True)

        return res

    @classmethod
    def traverse_paths(
        cls,
        include_paths,
        exclude_paths,
        file_suffixes=None,
        sorted=False,
        not_exists_ok=False,
    ) -> List["str"]:
        included_files_ = set()
        for path in include_paths:
            included_files_.update(cls.traverse_path(path, file_suffixes=file_suffixes))

        exclude_paths = ["./" + p.removeprefix("./") for p in exclude_paths]
        res = [
            f
            for f in included_files_
            if not any(f.startswith(exclude_path) for exclude_path in exclude_paths)
        ]
        if sorted:
            res.sort(reverse=True)
        return res

    @classmethod
    def compress_zst(cls, path):
        path = str(path).rstrip("/")
        path_obj = Path(path)
        is_dir = path_obj.is_dir()
        path_out = ""

        if Shell.check("which zstd"):
            if is_dir:
                # Compress just the directory's content, not full path
                parent = str(path_obj.parent.resolve())
                name = path_obj.name
                path_out = f"{parent}/{name}.tar.zst"
                Shell.check(
                    f"cd {parent} && rm -f {name}.tar.zst && tar -cf - {name} | zstd -c > {name}.tar.zst",
                    verbose=True,
                    strict=True,
                )
            elif path_obj.is_file():
                path_out = f"{path}.zst"
                Shell.check(
                    f"rm -f '{path_out}' && zstd -c '{path}' > '{path_out}'",
                    verbose=True,
                    strict=True,
                )
        return path_out

    @classmethod
    def compress_gz(cls, path):
        path = str(path).rstrip("/")
        path_obj = Path(path)
        is_dir = path_obj.is_dir()
        path_out = ""

        if Shell.check("which gzip"):
            if is_dir:
                # Compress just the directory's content, not full path
                parent = str(path_obj.parent.resolve())
                name = path_obj.name
                path_out = f"{parent}/{name}.tar.gz"
                Shell.check(
                    f"cd {parent} && rm -f {name}.tar.gz && tar -cf - {name} | gzip > {name}.tar.gz",
                    verbose=True,
                    strict=True,
                )
            elif path_obj.is_file():
                path_out = f"{path}.gz"
                Shell.check(
                    f"rm -f {path_out} && gzip -c '{path}' > '{path_out}'",
                    verbose=True,
                    strict=True,
                )
        return path_out

    @classmethod
    def compress_file(cls, path, no_strict=False):
        if Shell.check("which zstd"):
            return cls.compress_zst(path)
        elif Shell.check("which gzip"):
            return cls.compress_gz(path)
        else:
            path_out = path
            if not no_strict:
                raise RuntimeError(
                    f"Failed to compress file [{path}] no zstd or gz installed"
                )
        return path_out

    @classmethod
    def decompress_file(cls, path, path_to=None, remove_archive=False, no_strict=False):
        path = str(path)

        if path.endswith(".zst"):
            path_to = path_to or path.removesuffix(".zst")

            # Ensure zstd is installed
            if not Shell.check("which zstd", verbose=True, strict=not no_strict):
                print("ERROR: zstd is not installed. Cannot decompress artifact.")
                return False

            # Perform decompression
            res = Shell.check(
                f"zstd --decompress --force -o {quote(path_to)} {quote(path)}",
                verbose=True,
                strict=not no_strict,
            )
        else:
            raise NotImplementedError(
                f"Decompression for file type not supported: {path}"
            )

        if res and remove_archive:
            Shell.check(f"rm -f {quote(path)}", verbose=True)

        return res

    @classmethod
    def add_to_PATH(cls, path):
        path_cur = os.getenv("PATH", "")
        if path_cur:
            path += ":" + path_cur
        os.environ["PATH"] = path

    class Stopwatch:
        def __init__(self):
            self.start_time = datetime.now().timestamp()

        @property
        def duration(self) -> float:
            return datetime.now().timestamp() - self.start_time

    class Tee:
        def __init__(self, stdout=None):
            self.original_stdout = sys.stdout
            self.stdout = stdout

        def __enter__(self):
            class DualWriter:
                def __init__(self, original, duplicate):
                    self.original = original
                    self.duplicate = duplicate

                def write(self, message):
                    self.original.write(message)
                    self.duplicate.write(message)

                def flush(self):
                    self.original.flush()
                    self.duplicate.flush()

            if self.stdout:
                sys.stdout = DualWriter(self.original_stdout, self.stdout)
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            sys.stdout = self.original_stdout


class TeePopen:
    def __init__(
        self,
        command: str,
        log_file: Union[str, Path] = "",
        env: Optional[dict] = None,
        timeout: Optional[int] = None,
    ):
        self.command = command
        self.log_file_name = log_file
        self.log_file = None
        self.env = env or os.environ.copy()
        self.process = None  # type: Optional[subprocess.Popen]
        self.timeout = timeout
        self.timeout_exceeded = False
        self.terminated_by_sigterm = False
        self.terminated_by_sigkill = False
        self.log_rolling_buffer = deque(maxlen=100)

    def _check_timeout(self) -> None:
        if self.timeout is None:
            return
        time.sleep(self.timeout)
        print(
            f"WARNING: Timeout exceeded [{self.timeout}], send SIGTERM to [{self.process.pid}] and give a chance for graceful termination"
        )
        self.send_signal(signal.SIGTERM)
        time_wait = 0
        self.terminated_by_sigterm = True
        self.timeout_exceeded = True
        while self.process.poll() is None and time_wait < 100:
            print("wait...")
            wait = 5
            time.sleep(wait)
            time_wait += wait
        while self.process.poll() is None:
            print(f"WARNING: Still running, send SIGKILL to [{self.process.pid}]")
            self.send_signal(signal.SIGKILL)
            self.terminated_by_sigkill = True
            time.sleep(2)

    def __enter__(self) -> "TeePopen":
        if self.log_file_name:
            self.log_file = open(self.log_file_name, "w", encoding="utf-8")
        self.process = subprocess.Popen(
            self.command,
            shell=True,
            universal_newlines=True,
            env=self.env,
            start_new_session=True,  # signall will be sent to all children
            stderr=subprocess.STDOUT,
            stdout=subprocess.PIPE,
            bufsize=1,
            errors="backslashreplace",
        )
        time.sleep(1)
        print(f"Subprocess started, pid [{self.process.pid}]")
        if self.timeout is not None and self.timeout > 0:
            t = Thread(target=self._check_timeout)
            t.daemon = True  # does not block the program from exit
            t.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.wait()
        if self.log_file:
            self.log_file.close()

    def wait(self) -> int:
        if self.process.stdout is not None:
            for line in self.process.stdout:
                sys.stdout.write(line)

                if self.log_file:
                    self.log_file.write(line)
                self.log_rolling_buffer.append(line)
        return self.process.wait()

    def poll(self):
        return self.process.poll()

    def send_signal(self, signal_num):
        os.killpg(self.process.pid, signal_num)

    def get_latest_log(self, max_lines=20):
        buffer = list(self.log_rolling_buffer)

        # Search backwards for "Traceback"
        for i in range(len(buffer) - 1, -1, -1):
            if "Traceback" in buffer[i]:
                return "\n".join(buffer[i:])

        # Fallback: return last max_lines
        return "\n".join(buffer[-max_lines:])


if __name__ == "__main__":

    Utils.compress_gz("/tmp/test/")
