# Copyright 2025 the Hallmark Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Hallmark CLI entrypoint and command wiring."""


import click
from click import ClickException
from git.exc import GitError

from .downloader import DownloadError, download_remote_data
from .error import CloneError, DestinationExistsError, CheckoutError

from . import Repo  # from "__init__.py"


@click.group()
@click.version_option()
@click.pass_context
def hallmark(ctx):
    """Reproducibility is the hallmark of the scientific method.

    Hallmark is a lightweight package designed to version control and
    manage data products in a complex workflow.
    """
    if ctx.invoked_subcommand in [None, "init", "clone"]:
        return  # do nothing

    try:
        ctx.obj = Repo(".")
    except GitError as e:
        raise ClickException(
            f"Failed to open hallmark repository: {e}")


@hallmark.command(short_help="Initialize a hallmark repository.")
@click.argument("path")
def init(path):
    """Initialize a hallmark repository at PATH.

    If PATH ends with `.hm`, a bare repository is created.
    Otherwise, a `.hm` directory is created inside PATH.
    """
    try:
        Repo.init(path)
    except GitError as e:
        raise ClickException(
            f'Failed to initialize hallmark repository at "{path}": {e}')


@hallmark.command(short_help="Show information of the current directory.")
@click.pass_obj
def info(repo):
    """Show hallmark repository information of the current directory.

    Display local `.hm` and worktree locations for the current
    directory.
    """
    click.echo(f'dot-hallmark repo: "{repo.dothm.path}"')
    click.echo(f'hallmark worktree: "{repo.worktree}"')


@hallmark.command(short_help="Show worktree and staged hallmark state.")
@click.pass_obj
def status(repo):
    """Show hallmark status for the current branch and worktree."""
    snapshot = repo.status()

    click.echo(f'On branch {snapshot["branch"]}')

    staged = snapshot["staged"]
    worktree = snapshot["worktree"]
    untracked = snapshot["untracked"]

    def emit_section(title, entries, fg):
        if not entries:
            return
        click.echo("")
        click.secho(title, fg=fg)
        for label, paths in entries:
            for path in paths:
                click.echo("  " + click.style(f"{label}:   {path}", fg=fg))

    emit_section(
        "Changes to be committed:",
        [
            ("state", staged["state"]),
            ("new file", staged["added"]),
            ("modified", staged["modified"]),
            ("deleted", staged["deleted"]),
        ],
        "green",
    )
    emit_section(
        "Changes not staged for commit:",
        [
            ("modified", worktree["modified"]),
            ("deleted", worktree["deleted"]),
        ],
        "red",
    )
    if untracked:
        click.echo("")
        click.secho("Untracked files:", fg="red")
        for path in untracked:
            click.echo("  " + click.style(path, fg="red"))

    if not any([staged["state"], staged["added"], staged["modified"], staged["deleted"],
                worktree["modified"], worktree["deleted"], untracked]):
        click.echo("")
        click.echo("nothing to commit, working tree clean")


@hallmark.command(short_help="Add files to hallmark index.")
@click.option(
    "--regex",
    "encoding",
    is_flag=True,
    default=False,
    show_default=True,
    help="Enable regex-based encoding rules from config.yml.")
@click.argument("inputs", nargs=-1, required=True)
@click.pass_obj
def add(repo, encoding, inputs):
    """Add files to the hallmark index.

    `hallmark add [--regex] FORMAT` uses the branch format string workflow.
    `hallmark add "."` rebuilds the manifest from current files that match
    the branch `fmt` in `config.yml`.
    Explicit path inputs such as shell-expanded `*` are not supported yet
    with the parameter-based manifest format.
    """
    try:
        if len(inputs) == 1:
            pf = repo.add(inputs[0], encoding)
        else:
            pf = repo.add_paths(list(inputs))
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        raise ClickException(str(e))

    if pf.empty:
        click.echo("No files matched the format string.")
    else:
        click.echo("Changes to be committed")
        click.echo(pf.path.to_string(index=False, header=False))


@hallmark.command("set-config", short_help="Update hallmark branch config.")
@click.option("--fmt")
@click.option("--remote-name")
@click.option("--remote-url")
@click.option("--encoding", "encodings", multiple=True)
@click.pass_obj
def set_config(repo, fmt, remote_name, remote_url, encodings):
    """Update the current branch config.yml."""
    if not any([fmt, remote_name, remote_url, encodings]):
        raise ClickException("No config changes requested.")

    encoding_updates = {}
    for item in encodings:
        if "=" not in item:
            raise ClickException('encoding values must use FIELD=REGEX')
        field, regex = item.split("=", 1)
        if not field:
            raise ClickException('encoding values must use FIELD=REGEX')
        encoding_updates[field] = regex

    try:
        repo.set_config(
            fmt=fmt,
            remote_name=remote_name,
            remote_url=remote_url,
            encoding_updates=encoding_updates or None,
        )
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        raise ClickException(str(e))

    click.echo("Updated hallmark config.")


@hallmark.command(short_help="Commit changes to the repository.")
@click.option("-m", "message", required=True)
@click.pass_obj
def commit(repo, message):
    """Commit changes in the index to the hallmark repository.

    This is analogous to `git commit -m MESSAGE`.
    """
    if repo.commit(message):
        click.echo("Committed staged state changes.")
    else:
        click.echo("No changes added to commit.")


@hallmark.command(short_help="Show hallmark commit history.")
@click.pass_obj
def log(repo):
    """Show commit history for the hallmark state repository."""
    history = repo.log()
    if history:
        click.echo(history)


@hallmark.command(short_help="List hallmark branches.")
@click.pass_obj
def branch(repo):
    """List local hallmark branches."""
    snapshot = repo.branches()
    current = snapshot["current"]
    for name in snapshot["names"]:
        prefix = "*" if name == current else " "
        click.echo(f"{prefix} {name}")


@hallmark.command(short_help="Switch to another branch.")
@click.argument("target_branch")
@click.pass_obj
def checkout(repo, target_branch):
    """Switch branches and rewrite tracked files from branch state.

    This is analogous to `git checkout BRANCH`.
    If the branch does not exist, it is created from the current branch.
    Only hallmark-tracked files are rewritten; unrelated files are left
    alone unless they block restoration of a tracked path.
    """
    try:
        if repo.checkout(target_branch):
            click.echo(f'Switched to branch "{target_branch}".')
    except (GitError, RuntimeError, ValueError, FileNotFoundError, 
            CheckoutError) as e:
        raise ClickException(str(e))


@hallmark.command(short_help="Clone a hallmark repository from a remote URL.")
@click.argument("url")
@click.argument("path")
@click.option(
    "--no-fetch-data",
    is_flag=True,
    help="Skip downloading remote data files after clone.")
@click.option(
    "--max-workers",
    type=int,
    default=4,
    show_default=True,
    help="Number of concurrent downloads.")
def clone(url, path, no_fetch_data, max_workers):
    """Clone a hallmark repository from URL to PATH.

    By default, also downloads data files from the configured remote URL.
    Use --no-fetch-data to skip this step.

    Supports concurrent downloads for efficient retrieval of large datasets.
    """
    try:
        repo = Repo.clone(url, path, fetch_data=False)
        click.echo(f'Successfully cloned to "{path}"')

        if not no_fetch_data:
            _, worktree_path = Repo.lwpaths(path)
            if worktree_path is None:
                click.echo("Bare repository clone; skipping data download.")
                return

            click.echo("Downloading remote data files...")
            results = download_remote_data(
                repo,
                worktree_path,
                max_workers=max_workers,
                show_progress=True,
            )

            if results["failed"] == 0:
                mb_total = results["total_bytes"] / (1024 * 1024)
                click.echo(
                    f"Successfully downloaded {results['succeeded']} files "
                    f"({mb_total:.1f} MB)"
                )
            else:
                click.echo(
                    "Download completed with errors: "
                    f"{results['succeeded']} succeeded, "
                    f"{results['failed']} failed"
                )
                for error in results["errors"]:
                    click.echo(f"  - {error}", err=True)

                if results["failed"] == len(results["errors"]):
                    raise ClickException(
                        f"Failed to download {results['failed']} file(s)"
                    )

    except DestinationExistsError as e:
        click.echo(str(e), err=True)
    except CloneError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    except DownloadError as e:
        raise ClickException(str(e))
    except GitError as e:
        raise ClickException(str(e))
