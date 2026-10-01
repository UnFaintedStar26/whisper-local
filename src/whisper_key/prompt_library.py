# prompt_library.py
# Saved prompts for the Transcript History window. One hand-editable
# prompts.yaml in the app-data directory. The pure transitions live in
# apply(); mutate() is the only writer, so a crash cannot truncate the file.

import datetime
import hashlib
import os
import re
import sys
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Union

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import LiteralScalarString, SingleQuotedScalarString

from .utils import get_user_app_data_path

_FILE = 'prompts.yaml'
_LOCK = 'prompts.lock'
_MAX_CHARS = 200_000
_SAVE_ATTEMPTS = 5
_ID_RE = re.compile(r'^[0-9a-f]{12}$')
_HEADER = (
    'Saved prompts. Written by the Transcript History window; safe to edit by hand.'
)

# In-process first, then the OS lock. The opposite order deadlocks two threads.
_thread_lock = threading.Lock()


class PromptFileError(Exception):
    """The prompts file exists but cannot be parsed. Writers must leave it untouched."""


class PromptRejected(ValueError):
    """The bridge sent a command the library will not store."""


# rev is derived so a hand edit conflicts the same way a second window does.
@dataclass(frozen=True)
class Prompt:
    id: str
    title: str
    purpose: str
    note: str
    body: str
    source: str
    created: str
    updated: str

    @property
    def rev(self) -> str:
        blob = '\0'.join((self.title, self.purpose, self.note, self.body))
        return hashlib.sha1(blob.encode('utf-8')).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'title': self.title,
            'purpose': self.purpose,
            'note': self.note,
            'body': self.body,
            'source': self.source,
            'created': self.created,
            'updated': self.updated,
            'rev': self.rev,
        }


@dataclass(frozen=True)
class Capture:
    source: str
    body: str


@dataclass(frozen=True)
class Save:
    id: str | None
    title: str
    purpose: str
    note: str
    body: str
    source: str
    base_rev: str | None
    created: str | None = None


@dataclass(frozen=True)
class Delete:
    id: str
    base_rev: str | None


@dataclass(frozen=True)
class Wrote:
    changed: bool
    prompt: Prompt | None = None


@dataclass(frozen=True)
class Conflict:
    kind: Literal['deleted', 'changed']
    current: Prompt | None = None


Result = Union[Wrote, Conflict]


def prompts_path() -> Path:
    return Path(get_user_app_data_path()) / _FILE


# First non-blank line, capped at 80 characters on a word boundary.
def _derive_title(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) <= 80:
            return stripped
        cut = stripped[:80]
        space = cut.rfind(' ')
        if space > 0:
            return cut[:space].rstrip()
        return cut
    return ''


def _norm_title(title: str, body: str) -> str:
    title = title.strip()
    return title if title else _derive_title(body)


def _norm_purpose(purpose: str) -> str:
    return ' '.join(purpose.split())


class _SignatureChanged(Exception):
    """The prompts file moved between the read and the replace."""


# LF only, so a retry of the same text matches what was stored and rev stays put.
def _newlines(value: str) -> str:
    return value.replace('\r\n', '\n').replace('\r', '\n')


def _check_text(name: str, value) -> str:
    if not isinstance(value, str):
        raise PromptRejected(f'{name} must be a string')
    value = _newlines(value)
    if len(value) > _MAX_CHARS:
        raise PromptRejected(f'{name} is too long')
    return value


# Capture identity is the dictation timestamp plus a hash of the stored text.
# The body itself is not part of the key, so a later edit still dedupes.
def capture_source(timestamp: str, text: str) -> str:
    if not isinstance(timestamp, str):
        raise PromptRejected('timestamp must be a string')
    body = _check_text('body', text)
    digest = hashlib.sha1(body.encode('utf-8')).hexdigest()[:12]
    return f'{timestamp}|{digest}'


def _check_id(value) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise PromptRejected('id must be 12 lowercase hex characters')
    return value


def _require_body(body: str) -> str:
    body = _check_text('body', body)
    if not body.strip():
        raise PromptRejected('body is blank')
    return body


def _content(prompt: Prompt) -> tuple:
    return (prompt.title, prompt.purpose, prompt.note, prompt.body)


def _find(prompts: tuple, pid: str):
    for prompt in prompts:
        if prompt.id == pid:
            return prompt
    return None


def _mint(prompts: tuple, new_id: Callable[[], str]) -> str:
    taken = {prompt.id for prompt in prompts}
    for _ in range(8):
        pid = new_id()
        if isinstance(pid, str) and _ID_RE.fullmatch(pid) and pid not in taken:
            return pid
    raise PromptRejected('could not mint an id')


def _make(pid: str, title: str, purpose: str, note: str, body: str,
          source: str, created: str, updated: str) -> Prompt:
    return Prompt(pid, title, purpose, note, body, source, created, updated)


# Pure transition. Same fields converge even when base_rev is stale.
def apply(prompts: tuple, cmd, now: str, new_id: Callable[[], str]) -> Result:
    if isinstance(cmd, Capture):
        body = _require_body(cmd.body)
        source = _check_text('source', cmd.source)
        if source:
            existing = next((p for p in prompts if p.source == source), None)
            if existing is not None:
                return Wrote(False, existing)
        pid = _mint(prompts, new_id)
        prompt = _make(pid, _derive_title(body), '', '', body, source, now, now)
        return Wrote(True, prompt)

    if isinstance(cmd, Save):
        body = _require_body(cmd.body)
        title = _norm_title(_check_text('title', cmd.title), body)
        purpose = _norm_purpose(_check_text('purpose', cmd.purpose))
        note = _check_text('note', cmd.note)
        source = _check_text('source', cmd.source)
        fields = (title, purpose, note, body)
        if cmd.id is None:
            pid = _mint(prompts, new_id)
            return Wrote(True, _make(pid, title, purpose, note, body, source, now, now))
        pid = _check_id(cmd.id)
        stored = _find(prompts, pid)
        if stored is None:
            if cmd.base_rev is None:
                created = cmd.created or now
                return Wrote(True, _make(pid, title, purpose, note, body, source, created, now))
            return Conflict('deleted', None)
        if _content(stored) == fields:
            return Wrote(False, stored)
        if stored.rev != cmd.base_rev:
            return Conflict('changed', stored)
        return Wrote(True, _make(
            stored.id, title, purpose, note, body, source, stored.created, now,
        ))

    if isinstance(cmd, Delete):
        pid = _check_id(cmd.id)
        stored = _find(prompts, pid)
        if stored is None:
            return Wrote(False, None)
        if stored.rev != cmd.base_rev:
            return Conflict('changed', stored)
        return Wrote(True, None)

    raise PromptRejected('unknown command')


def _yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 10**6
    return yaml


# Hand edits may store dates and other scalars. Mappings and sequences are not text.
def _plain(value, name: str) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return _newlines(value)
    if isinstance(value, (Mapping, Sequence)):
        raise PromptFileError(f'{name} is not text')
    if isinstance(value, datetime.datetime):
        return value.replace(microsecond=0).isoformat(timespec='seconds')
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value)


def _prompt_from_item(item) -> Prompt:
    if not isinstance(item, dict):
        raise PromptFileError('a prompt entry is not a mapping')
    pid = _plain(item.get('id'), 'id').strip().lower()
    if not _ID_RE.fullmatch(pid):
        raise PromptFileError('a prompt id is not 12 lowercase hex characters')
    body = _plain(item.get('body'), 'body')
    title = _plain(item.get('title'), 'title')
    return Prompt(
        id=pid,
        title=title if title.strip() else _derive_title(body),
        purpose=_plain(item.get('purpose'), 'purpose'),
        note=_plain(item.get('note'), 'note'),
        body=body,
        source=_plain(item.get('source'), 'source'),
        created=_plain(item.get('created'), 'created'),
        updated=_plain(item.get('updated'), 'updated'),
    )


def _empty_doc() -> CommentedMap:
    doc = CommentedMap()
    doc['prompts'] = CommentedSeq()
    doc.yaml_set_start_comment(_HEADER + '\n')
    return doc


# Missing file is an empty library. A file we cannot parse is never replaced.
def _load_doc(path: Path):
    if not path.exists():
        return _empty_doc(), []
    try:
        with open(path, encoding='utf-8') as handle:
            loaded = _yaml().load(handle)
    except OSError:
        raise
    except Exception as exc:
        raise PromptFileError(f'cannot parse {path.name}') from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get('prompts'), list):
        raise PromptFileError(f'{path.name} is not a prompts list')
    prompts = []
    seen = set()
    for item in loaded['prompts']:
        prompt = _prompt_from_item(item)
        if prompt.id in seen:
            raise PromptFileError(f'duplicate prompt id {prompt.id}')
        seen.add(prompt.id)
        prompts.append(prompt)
    return loaded, prompts


# `|` blocks only for text YAML can re-read unchanged. Anything else stays a
# plain str so the emitter double-quotes it and escapes the odd characters.
def _literal_block_ok(text: str) -> bool:
    for ch in text:
        if ch in '\n\t':
            continue
        code = ord(ch)
        if code < 0x20 or code == 0x7F or code == 0x85:
            return False
        if ch in '\u2028\u2029\ufeff':
            return False
        if 0xD800 <= code <= 0xDFFF or code >= 0xFFFE:
            return False
    return True


def _block(text: str):
    if '\n' in text and _literal_block_ok(text):
        return LiteralScalarString(text)
    return text


def _quoted(text: str) -> SingleQuotedScalarString:
    return SingleQuotedScalarString(text)


def _fill(item: CommentedMap, prompt: Prompt) -> None:
    item['id'] = _quoted(prompt.id)
    item['title'] = prompt.title
    item['purpose'] = prompt.purpose
    item['note'] = _block(prompt.note)
    item['body'] = _block(prompt.body)
    item['source'] = _quoted(prompt.source)
    item['created'] = _quoted(prompt.created)
    item['updated'] = _quoted(prompt.updated)


def _commit(doc, cmd, result: Wrote) -> None:
    seq = doc['prompts']
    if isinstance(cmd, Delete):
        for index, item in enumerate(list(seq)):
            if isinstance(item, dict) and _plain(item.get('id'), 'id').strip().lower() == cmd.id:
                del seq[index]
                return
        return
    prompt = result.prompt
    for item in seq:
        if isinstance(item, dict) and _plain(item.get('id'), 'id').strip().lower() == prompt.id:
            _fill(item, prompt)
            return
    item = CommentedMap()
    _fill(item, prompt)
    seq.append(item)


def _file_sig(path: Path):
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _written_prompts(doc) -> tuple:
    return tuple(_prompt_from_item(item) for item in doc['prompts'])


# Flush the temp file, prove it reloads as the prompts we wrote, then replace
# only if the destination was not hand-edited after we read it.
def _atomic_write(path: Path, doc, sig) -> None:
    tmp = path.parent / (path.name + '.tmp')
    expected = _written_prompts(doc)
    with open(tmp, 'w', encoding='utf-8', newline='\n') as handle:
        _yaml().dump(doc, handle)
        handle.flush()
        os.fsync(handle.fileno())
    _, loaded = _load_doc(tmp)
    if tuple(loaded) != expected:
        raise PromptFileError(f'{path.name} round-trip failed')
    last_error = None
    for attempt in range(_SAVE_ATTEMPTS):
        if _file_sig(path) != sig:
            raise _SignatureChanged()
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt == _SAVE_ATTEMPTS - 1:
                break
            time.sleep(0.02)
    raise last_error


@contextmanager
def _os_lock(lock_path: Path):
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o666)
    try:
        if sys.platform == 'win32':
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            if os.fstat(fd).st_size < 1:
                os.write(fd, b'\0')
                os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec='seconds')


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# Blank bodies stay in the file but are not part of the transition or the list.
def _visible(prompts: list) -> tuple:
    return tuple(prompt for prompt in prompts if prompt.body.strip())


def load_prompts() -> list:
    _, prompts = _load_doc(prompts_path())
    visible = [prompt for prompt in prompts if prompt.body.strip()]
    visible.sort(key=lambda prompt: prompt.updated, reverse=True)
    return visible


def _mutate_once(path: Path, cmd) -> Result:
    sig = _file_sig(path)
    doc, prompts = _load_doc(path)
    result = apply(_visible(prompts), cmd, _now(), _new_id)
    if isinstance(result, Wrote) and result.changed:
        _commit(doc, cmd, result)
        _atomic_write(path, doc, sig)
    return result


# Redo the whole read when a hand edit lands in the window before replace.
def mutate(cmd) -> Result:
    with _thread_lock:
        path = prompts_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _os_lock(path.parent / _LOCK):
            for _ in range(_SAVE_ATTEMPTS):
                try:
                    return _mutate_once(path, cmd)
                except _SignatureChanged:
                    continue
            raise PromptFileError(f'{path.name} changed during save')
