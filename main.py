import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile


PYTHON_EMBED_URLS = {
    "win32": (
        "https://www.python.org/ftp/python/3.8.1/python-3.8.1-embed-win32.zip"
    ),
    "amd64": (
        "https://www.python.org/ftp/python/3.8.1/python-3.8.1-embed-amd64.zip"
    ),
}

PIPX_VERSION = "0.15.1.3"

BUILD_VERSION = None


def retrieve_python(url: str, dl_dir: pathlib.Path, build_dir: pathlib.Path):
    archive = dl_dir.joinpath(url.rsplit("/", 1)[-1])
    if not archive.exists():
        urllib.request.urlretrieve(url, archive)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(build_dir)


def retrieve_pipx(build_dir: pathlib.Path):
    env = os.environ.copy()
    env.update({
        "PIP_REQUIRE_VIRTUALENV": "false",
        "PIP_DISABLE_PIP_VERSION_CHECK": "true",
    })
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            f"pipx=={PIPX_VERSION}",
            "setuptools",  # TODO: Remove this for pipx>0.15.1.3.
            "--target",
            os.fspath(build_dir),
        ],
        env=env,
        check=True,
    )


_DEFAULT_PYTHON_PATCH = """\
def _find_default_python():
    import shutil
    py = shutil.which("py")
    if py:
        return py
    python = shutil.which("python")
    if "WindowsApps" not in python:
        return python
    # Special treatment to detect Windows Store stub.
    # https://twitter.com/zooba/status/1212454929379581952
    import subprocess
    proc = subprocess.run(
        [python, "-V"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        # Cover the 9009 return code pre-emptively.
        raise EnvironmentError("no available Python found")
    if not proc.stdout.strip():
        # A real Python should print version, Windows Store stub won't.
        raise EnvironmentError("no available Python found")
    return python  # This executable seems to work.

DEFAULT_PYTHON = _find_default_python()
"""


def _patch_constants_py(path: pathlib.Path):
    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
        newline = f.newlines

    if not isinstance(newline, str):
        newline = "\n"

    with path.open("w", encoding="utf-8", newline=newline) as f:
        for line in lines:
            if line.startswith("DEFAULT_PYTHON = "):
                f.write(_DEFAULT_PYTHON_PATCH)
            else:
                f.write(line)


def patch_pipx(build_dir: pathlib.Path):
    _patch_constants_py(build_dir.joinpath("pipx", "constants.py"))


def create_archive(source: pathlib.Path, target: pathlib.Path):
    with zipfile.ZipFile(target, "w") as zf:
        for dirpath, _, filenames in os.walk(source):
            # Don't need to package dist info.
            if os.path.splitext(dirpath)[-1] == ".dist-info":
                continue
            # Do not package entry points. They will be broken due
            # to we installing to a different location anyway.
            if dirpath == os.path.join(source, "bin"):
                continue
            for fn in filenames:
                absname = os.path.join(dirpath, fn)
                relname = os.path.relpath(absname, source)
                zf.write(absname, relname)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().with_name("build"),
    )
    parser.add_argument(
        "--dist",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().with_name("dist"),
    )
    parser.add_argument(
        "--variant",
        choices=sorted(PYTHON_EMBED_URLS.keys()),
        required=True,
    )
    ns = parser.parse_args(argv)

    dist_name = f"pipx-standalone-{ns.variant}-{PIPX_VERSION}"
    if BUILD_VERSION:
        dist_name += f"-{BUILD_VERSION}"

    build_dir = ns.build.joinpath(dist_name)
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)

    dist_dir = ns.dist
    dist_dir.mkdir(parents=True, exist_ok=True)

    print(f"Building into: {build_dir}")

    target = dist_dir.joinpath(f"{build_dir.name}.zip")
    if target.exists():
        raise FileExistsError(target)

    print(f"Downloading {PYTHON_EMBED_URLS[ns.variant]}")
    retrieve_python(PYTHON_EMBED_URLS[ns.variant], ns.build, build_dir)

    # pip would emit output so we don't.
    retrieve_pipx(build_dir)

    print(f"Patching {build_dir.joinpath('pipx')}")
    patch_pipx(build_dir)

    print("Creating archive...", end=" ", flush=True)
    create_archive(build_dir, target)
    print(f"Done: {target}")


if __name__ == "__main__":
    main()
