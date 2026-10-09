"""The mail seam. A MailSource reads a mailbox and nothing else: no send, no move, no delete, no flag. Implementations:
outlook_com.py (classic Outlook, read-only) and graph.py (Mail.Read). Tests use tests/fakes/fake_mailsource.py."""
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator


@dataclass
class Store:
    id: str
    name: str
    cached: bool  # true only for a cached Exchange store: never an online archive, a public folder or a changed sync window


@dataclass
class Folder:
    store_id: str
    id: str
    path: str  # relative to the store root, '/' separated, e.g. "Inbox/Projects"


@dataclass
class Item:
    """Fields that need no protected property. Times are UTC 'YYYY-MM-DDTHH:MM:SSZ'."""
    entry_id: str
    conversation_id: str
    subject: str
    received: str
    modified: str
    message_class: str = "IPM.Note"
    ref: Any = field(default=None, repr=False)  # the source's own object for body() and attachments()


@dataclass
class Attachment:
    name: str
    size: int
    save: Callable[[str], None]  # write the attachment to this path; only called for unlabelled items


class PolicyBlock(Exception):
    """A protected read was refused, failed or is waiting on a security prompt: a hard stop, never retried."""


class MailSource:
    def stores(self) -> "list[Store]":
        raise NotImplementedError

    def folders(self, store: Store) -> "list[Folder]":
        raise NotImplementedError

    def items(self, folder: Folder, since: "str | None", after_entry_ids: "set[str]") -> "Iterator[Item]":
        """Items with modified >= since, oldest modification first; an item whose modified equals `since` and whose id is in
        `after_entry_ids` was already handled and is left out."""
        raise NotImplementedError

    def body(self, item: Item, headers_only: bool = False) -> dict:
        """{"text","html","from","to","cc","message_id"}; with headers_only the text and html are None (labelled items)."""
        raise NotImplementedError

    def attachments(self, item: Item) -> "list[Attachment]":
        raise NotImplementedError

    def labels(self, item: Item) -> "list[str]":
        """Sensitivity labels found in the message headers (msip_labels); [] when there are none."""
        raise NotImplementedError
