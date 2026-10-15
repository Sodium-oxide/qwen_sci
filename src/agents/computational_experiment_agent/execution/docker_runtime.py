"""Isolate programs using read-only volumes and a bounded temporary output volume."""

import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
from pathlib import Path

from src.pipeline.science_run import utc_now

from ..artifacts import safe_path
from ..contracts import CapabilityReport, ExecutionRequest, require_contract
from .runtime import RunAuthorization


class RuntimeCancelled(RuntimeError):
    pass


class DockerRuntime:
    def __init__(self, command: tuple[str, ...] | None = None, *, max_output_bytes: int = 64_000_000):
        self.command = command or self.discover()
        self.max_output_bytes = max_output_bytes
        self.deadline, self.cancel_check = None, None

    @staticmethod
    def discover() -> tuple[str, ...]:
        if shutil.which("docker"):
            return ("docker",)
        if os.name == "nt" and shutil.which("wsl.exe"):
            return ("wsl.exe", "-d", "Ubuntu-24.04", "-u", "root", "--", "docker")
        return ("docker",)

    def remaining(self, timeout: float = 30) -> float:
        if self.cancel_check and self.cancel_check():
            raise RuntimeCancelled("execution_cancelled")
        value = timeout if self.deadline is None else min(timeout, self.deadline - time.monotonic())
        if value <= 0:
            raise TimeoutError("execution_deadline_exceeded")
        return value

    def invoke(self, args: list[str], *, timeout: float = 30, cleanup: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run([*self.command, *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout if cleanup else self.remaining(timeout), check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    def probe(self, environment_id: str) -> CapabilityReport:
        try:
            daemon = self.invoke(["info", "--format", "{{.ServerVersion}}"], timeout=10)
            image = self.invoke(["image", "inspect", environment_id], timeout=10) if daemon.returncode == 0 else daemon
            return CapabilityReport("docker", image.returncode == 0,
                "" if image.returncode == 0 else "container_daemon_or_image_unavailable",
                {"environment_id": environment_id, "daemon_version": daemon.stdout.strip()})
        except TimeoutError:
            raise
        except (OSError, subprocess.TimeoutExpired):
            return CapabilityReport("docker", False, "container_runtime_unavailable")

    def cleanup_resources(self, name: str) -> list[str]:
        failures = []
        for args in (["rm", "-f", name], ["rm", "-f", name + "-output-holder"],
                     ["rm", "-f", name + "-project-stage"], ["rm", "-f", name + "-inputs-stage"],
                     ["volume", "rm", name + "-project"], ["volume", "rm", name + "-inputs"],
                     ["volume", "rm", name + "-output"]):
            try:
                result = self.invoke(list(args), timeout=5, cleanup=True)
                if result.returncode and "No such" not in result.stderr:
                    failures.append(result.stderr[:300])
            except (OSError, subprocess.TimeoutExpired) as error:
                failures.append(str(error)[:300])
        return failures

    def cancel(self, container_name: str) -> None:
        self.cleanup_resources(container_name)

    def stage_volume(self, directory: Path, name: str, image_id: str) -> None:
        created = self.invoke(["volume", "create", name])
        if created.returncode:
            raise ValueError("staging_volume_unavailable")
        helper = name + "-stage"
        try:
            created = self.invoke(["create", "--name", helper, "--network", "none", "--mount",
                f"type=volume,src={name},dst=/staging", "--entrypoint", "python", image_id, "-c", "pass"])
            if created.returncode:
                raise ValueError("staging_container_unavailable")
            archive, size, count = io.BytesIO(), 0, 0
            with tarfile.open(fileobj=archive, mode="w", format=tarfile.PAX_FORMAT) as bundle:
                for path in directory.rglob("*"):
                    self.remaining()
                    count += 1
                    if count > 10000:
                        raise ValueError("staging_input_limits_exceeded")
                    relative = path.relative_to(directory).as_posix()
                    safe_path(directory, relative)
                    if path.is_file():
                        size += path.stat().st_size
                        if size > 64_000_000 or count > 10000:
                            raise ValueError("staging_input_limits_exceeded")
                        metadata = tarfile.TarInfo(relative)
                        metadata.size, metadata.mode, metadata.uid, metadata.gid = path.stat().st_size, 0o644, 0, 0
                        with path.open("rb") as source:
                            bundle.addfile(metadata, source)
            copied = subprocess.run([*self.command, "cp", "-", helper + ":/staging"], input=archive.getvalue(),
                capture_output=True, timeout=self.remaining(30),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if copied.returncode:
                raise ValueError("staging_copy_failed:" + copied.stderr.decode(errors="replace")[:1000])
        finally:
            self.invoke(["rm", "-f", helper], timeout=5, cleanup=True)

    def import_output(self, holder: str, destination: Path) -> None:
        with tempfile.TemporaryFile() as archive:
            process = subprocess.Popen([*self.command, "cp", holder + ":/output/.", "-"], stdout=archive,
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                while process.poll() is None:
                    self.remaining(15)
                    if archive.tell() > self.max_output_bytes + 10_000_000:
                        raise ValueError("output_archive_size_exceeded")
                    time.sleep(.1)
                if process.returncode:
                    raise ValueError("output_import_failed")
                if archive.tell() > self.max_output_bytes + 10_000_000:
                    raise ValueError("output_archive_size_exceeded")
                archive.seek(0)
                with tarfile.open(fileobj=archive) as bundle:
                    size, count = 0, 0
                    for member in bundle:
                        self.remaining()
                        count += 1
                        if count > 10000:
                            raise ValueError("too_many_output_files")
                        relative = member.name.removeprefix("./")
                        if relative in {".", ""} and member.isdir():
                            continue
                        target = safe_path(destination, relative)
                        if not (member.isfile() or member.isdir()) or member.issym() or member.islnk():
                            raise ValueError("linked_or_special_output_file")
                        size += member.size
                        if size > self.max_output_bytes:
                            raise ValueError("output_size_exceeded")
                        if member.isdir():
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with bundle.extractfile(member) as source, target.open("wb") as output:
                                shutil.copyfileobj(source, output)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

    def run(self, request: ExecutionRequest, authorization: RunAuthorization, *, cancel=None, on_started=None) -> dict:
        authorization.validate(request)
        request.output_dir.mkdir(parents=True, exist_ok=True)
        name = "qwensci-ce-" + uuid.uuid4().hex
        started_at, started = utc_now(), time.monotonic()
        self.deadline, self.cancel_check = started + request.max_wall_seconds, cancel
        status, error, exit_code, environment = "FAILED", "", None, {}
        stdout_path, stderr_path = request.output_dir / "stdout.log", request.output_dir / "stderr.log"
        stdout_path.touch()
        stderr_path.touch()
        cleanup_errors = []
        if on_started:
            on_started(name)
        try:
            capability = self.probe(request.environment_id)
            if not capability.available:
                status, error = "ENVIRONMENT_UNAVAILABLE", capability.reason
            else:
                inspected = self.invoke(["image", "inspect", request.environment_id, "--format", "{{.Id}}"])
                digest = inspected.stdout.strip()
                if not digest.startswith("sha256:"):
                    raise ValueError("cannot_pin_image")
                environment = {"image_id": digest, "runtime": "docker", "network_enabled": request.network_enabled,
                    "cpu_cores": request.cpu_cores, "memory_mb": request.memory_mb, "container_name": name}
                for folder, suffix in ((request.project_dir, "project"), (request.input_dir, "inputs")):
                    if not folder.is_dir():
                        raise ValueError("missing_input_directory")
                    self.stage_volume(folder, name + "-" + suffix, digest)
                created = self.invoke(["volume", "create", "--driver", "local", "--opt", "type=tmpfs",
                    "--opt", "device=tmpfs", "--opt", f"o=size={self.max_output_bytes},nr_inodes=10000,uid=65534,gid=65534,mode=700",
                    name + "-output"])
                if created.returncode:
                    raise ValueError("bounded_output_volume_unavailable")
                holder = name + "-output-holder"
                held = self.invoke(["run", "-d", "--name", holder, "--read-only", "--network", "none",
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "64m", "--pids-limit", "8",
                    "--mount", f"type=volume,src={name}-output,dst=/output", "--entrypoint", "python", digest,
                    "-I", "-c", "import time;time.sleep(86400)"])
                if held.returncode:
                    raise ValueError("output_holder_failed:" + held.stderr[:1000])
                lock = self.invoke(["exec", holder, "python", "-I", "-c",
                    "from pathlib import Path;print(Path('/opt/environment.lock').read_text() if Path('/opt/environment.lock').exists() else 'unavailable')"])
                environment["dependency_lock"] = lock.stdout[:32000] if lock.returncode == 0 else "unavailable"
                self.remaining()
                args = ["create", "--name", name, "--read-only", "--user", "65534:65534",
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "128",
                    "--cpus", str(request.cpu_cores), "--memory", f"{request.memory_mb}m",
                    "--memory-swap", f"{request.memory_mb}m", "--network", "bridge" if request.network_enabled else "none",
                    "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m,mode=1777",
                    "--mount", f"type=volume,src={name}-project,dst=/project,readonly",
                    "--mount", f"type=volume,src={name}-inputs,dst=/inputs,readonly",
                    "--mount", f"type=volume,src={name}-output,dst=/output",
                    "--workdir", "/project", "--env", "HOME=/tmp", "--env", "PYTHONDONTWRITEBYTECODE=1",
                    "--env", "OMP_NUM_THREADS=" + str(request.cpu_cores), "--env", "OPENBLAS_NUM_THREADS=" + str(request.cpu_cores),
                    "--log-driver", "local", "--log-opt", "max-size=8m", "--log-opt", "max-file=1", "--log-opt", "compress=false",
                    "--entrypoint", request.command[0], digest, *request.command[1:]]
                created = self.invoke(args)
                if created.returncode:
                    raise ValueError("container_create_failed:" + created.stderr[:2000])
                launched = self.invoke(["start", name])
                if launched.returncode:
                    raise ValueError("container_start_failed:" + launched.stderr[:2000])
                while True:
                    self.remaining()
                    state = self.invoke(["inspect", name, "--format", "{{.State.Running}} {{.State.ExitCode}}"], timeout=10)
                    if state.returncode:
                        raise ValueError("container_state_unavailable")
                    running, code = state.stdout.strip().split()
                    if running == "false":
                        exit_code = int(code)
                        status = "COMPLETED" if exit_code == 0 else "FAILED"
                        break
                    time.sleep(.2)
                logs = self.invoke(["logs", name])
                stdout_path.write_text(logs.stdout[:8_000_000], encoding="utf-8")
                stderr_path.write_text(logs.stderr[:8_000_000], encoding="utf-8")
                if status == "COMPLETED":
                    self.import_output(holder, request.output_dir / "raw")
        except RuntimeCancelled as failure:
            status, error = "CANCELLED", str(failure)
        except (TimeoutError, subprocess.TimeoutExpired) as failure:
            status, error = "TIMEOUT", str(failure)
        except (OSError, ValueError, tarfile.TarError) as failure:
            status, error = "FAILED", str(failure)
        finally:
            cleanup_errors = self.cleanup_resources(name)
            self.deadline, self.cancel_check = None, None
        return require_contract({"schema_version": "computational_execution_v1", "execution_id": name,
            "experiment_id": request.experiment_id, "source_binding": dict(request.source_binding),
            "protocol_version": request.protocol_version, "implementation_version": request.implementation_version,
            "purpose": request.purpose, "status": status, "command": list(request.command), "environment": environment,
            "started_at": started_at, "finished_at": utc_now(), "elapsed_seconds": time.monotonic() - started,
            "exit_code": exit_code, "resource_usage": {"cleanup_errors": cleanup_errors},
            "output_dir": str(request.output_dir), "stdout_path": str(stdout_path), "stderr_path": str(stderr_path),
            "authorization_id": authorization.authorization_id, "error": error})
