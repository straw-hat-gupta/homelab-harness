from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Any

from django.contrib.auth import get_user_model
from django.db import transaction

from context.models import ProjectContext
from projects.models import Projects

Message = Dict[str, str]  # {"role": "user"|"assistant"|"system"|"tool", "content": "..."}

MAX_SIZE = 3_000  # token budget (cl100k_base; ~3 chars/token for typical English)


def _char_size(msgs: List[Message]) -> int:
    """Character-based size estimate. Kept for tests and as a fallback."""
    return sum(len(m.get("content", "")) + len(m.get("role", "")) + 2 for m in msgs)


def _token_size(msgs: List[Message]) -> int:
    """Count tokens using tiktoken (cl100k_base, compatible with GPT-4/4o models)."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return sum(
            len(enc.encode(m.get("content", ""))) + len(enc.encode(m.get("role", ""))) + 4
            for m in msgs
        )
    except Exception:
        # Fall back to character heuristic (1 token ≈ 3 chars)
        return _char_size(msgs) // 3


# ---------------------------------------------------------------------------
# DB-backed store
# ---------------------------------------------------------------------------

class DbContextStore:
    def _get_project(self, user_id: str, project_id: str) -> Optional[Projects]:
        """Load a project owned by a Supabase user.

        Args:
            user_id: Supabase UID of the project owner.
            project_id: Project primary key as a string.

        Returns:
            Matching project, or None.
        """
        try:
            pid = int(project_id)
        except (ValueError, TypeError):
            return None
        User = get_user_model()
        try:
            user = User.objects.get(supabase_uid=user_id)
            return Projects.objects.get(pk=pid, user=user)
        except Exception:
            return None

    def load(self, user_id: str, project_id: str) -> Optional[dict]:
        """Load persisted conversation context for a project.

        Args:
            user_id: Supabase UID of the project owner.
            project_id: Project primary key as a string.

        Returns:
            Serialized context dictionary, or None.
        """
        project = self._get_project(user_id, project_id)
        if project is None:
            return None
        rows = (
            ProjectContext.objects
            .filter(project=project, sequence__gte=project.active_context_from)
            .order_by("sequence")
        )
        messages: List[Message] = []
        sequences: List[int] = []
        for r in rows:
            messages.append({"role": r.role, "content": r.content})
            sequences.append(r.sequence)
        return {
            "user_id": user_id,
            "project_id": project_id,
            "messages": messages,
            "sequences": sequences,
            "active_from": project.active_context_from,
        }

    def save(self, ctx: "ChatContext") -> None:
        """Persist unsaved messages and pruning state.

        Args:
            ctx: Chat context to persist.

        Returns:
            None.
        """
        project = self._get_project(ctx.user_id, ctx.project_id)
        if project is None:
            return

        unsaved = [i for i, seq in enumerate(ctx._sequences) if seq is None]
        active_from_changed = ctx._active_from != project.active_context_from

        if not unsaved and not active_from_changed:
            return

        with transaction.atomic():
            if unsaved:
                last = (
                    ProjectContext.objects
                    .filter(project=project)
                    .select_for_update()
                    .order_by("-sequence")
                    .first()
                )
                next_seq = (last.sequence if last else 0) + 1
                new_rows = []
                for i in unsaved:
                    new_rows.append(ProjectContext(
                        project=project,
                        role=ctx.messages[i]["role"],
                        content=ctx.messages[i]["content"],
                        sequence=next_seq,
                    ))
                    ctx._sequences[i] = next_seq
                    next_seq += 1
                ProjectContext.objects.bulk_create(new_rows, batch_size=500)

            if active_from_changed:
                project.active_context_from = ctx._active_from
                project.save(update_fields=["active_context_from", "updated_at"])


# ---------------------------------------------------------------------------
# ChatContext: in-memory pruning + DB persistence
# ---------------------------------------------------------------------------

@dataclass
class ChatContext:
    user_id: str
    project_id: str
    max_size: int = MAX_SIZE
    size_fn: Callable[[List[Message]], int] = field(default=_token_size, repr=False)
    messages: List[Message] = field(default_factory=list)

    _store: Optional[DbContextStore] = field(default=None, repr=False)
    _next_role: str = field(default="user", repr=False)
    # Parallel to messages: sequence number if row exists in DB, else None.
    _sequences: List[Optional[int]] = field(default_factory=list, repr=False)
    # active_context_from value last read from DB; advanced when messages are pruned.
    _active_from: int = field(default=0, repr=False)

    def __call__(self, *args: Any, **kwargs: Any) -> str:
        transcript = self.as_transcript()
        return (
            "You are a helpful assistant. Honor prior decisions in this conversation.\n"
            f"User ID: {self.user_id} | Project: {self.project_id}\n"
            "=== Conversation So Far (may be pruned) ===\n"
            f"{transcript}\n"
            "=== End Conversation History ==="
        )

    def add_message(self, content: str, role: Optional[str] = None) -> None:
        """Append a message and persist the context.

        Args:
            content: Message content.
            role: Optional explicit message role.

        Returns:
            None.
        """
        role = role or self._auto_role()
        self.messages.append({"role": role, "content": content})
        self._sequences.append(None)
        self._prune()
        self._autosave()

    def add_user(self, content: str) -> None:
        """Append a user message.

        Args:
            content: Message content.

        Returns:
            None.
        """
        self.add_message(content, role="user")

    def add_assistant(self, content: str) -> None:
        """Append an assistant message.

        Args:
            content: Message content.

        Returns:
            None.
        """
        self.add_message(content, role="assistant")

    def as_messages(self) -> List[Message]:
        """Return messages in planner-compatible format.

        Returns:
            Copy of conversation messages.
        """
        return list(self.messages)

    def as_transcript(self) -> str:
        """Render messages as a plain-text transcript.

        Returns:
            Conversation transcript string.
        """
        return "\n".join(f"{m['role'].capitalize()}: {m['content']}" for m in self.messages)

    def to_dict(self) -> dict:
        """Serialize the chat context.

        Returns:
            Dictionary representation of the context.
        """
        return {"user_id": self.user_id, "project_id": self.project_id, "messages": list(self.messages)}

    @classmethod
    def from_dict(cls, data: dict, *, store: Optional[DbContextStore] = None) -> "ChatContext":
        """Build a chat context from serialized data.

        Args:
            data: Serialized context dictionary.
            store: Optional backing store for autosave.

        Returns:
            Hydrated chat context.
        """
        ctx = cls(
            user_id=data["user_id"],
            project_id=data["project_id"],
            messages=list(data.get("messages", [])),
        )
        ctx._store = store
        ctx._sequences = list(data.get("sequences", [None] * len(ctx.messages)))
        ctx._active_from = data.get("active_from", 0)
        if ctx.messages and ctx.messages[-1]["role"] == "user":
            ctx._next_role = "assistant"
        return ctx

    def _auto_role(self) -> str:
        """Return the next alternating message role.

        Returns:
            Role name for the next message.
        """
        role = self._next_role
        self._next_role = "assistant" if role == "user" else "user"
        return role

    def _drop_at(self, idx: int) -> None:
        """Pop message and its sequence; advance _active_from past the dropped DB row."""
        seq = self._sequences[idx] if idx < len(self._sequences) else None
        self.messages.pop(idx)
        if idx < len(self._sequences):
            self._sequences.pop(idx)
        # Advance the LLM context window cursor so load() skips this row next time.
        if seq is not None and self._sequences:
            next_saved = next((s for s in self._sequences if s is not None), None)
            if next_saved is not None:
                self._active_from = next_saved

    def _prune(self) -> None:
        """Prune old messages until the context fits the size budget.

        Returns:
            None.
        """
        while len(self.messages) > 1 and self.size_fn(self.messages) > self.max_size:
            drop_idx = next(
                (i for i, m in enumerate(self.messages) if m["role"] in ("system", "tool")),
                0,
            )
            self._drop_at(drop_idx)
        if self.size_fn(self.messages) > self.max_size and len(self.messages) > 1:
            self._drop_at(0)

    def _autosave(self) -> None:
        """Persist the context when a store is configured.

        Returns:
            None.
        """
        if self._store:
            self._store.save(self)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_ctx(user_id: str, project_id: str, *, max_size: Optional[int] = None) -> ChatContext:
    """Load or create chat context for a user/project pair.

    Args:
        user_id: Supabase UID of the project owner.
        project_id: Project primary key as a string.
        max_size: Optional context size budget override.

    Returns:
        Chat context instance.
    """
    store = DbContextStore()
    data = store.load(user_id, project_id)
    if data:
        ctx = ChatContext.from_dict(data, store=store)
        if max_size is not None:
            ctx.max_size = max_size
    else:
        ctx = ChatContext(user_id=user_id, project_id=project_id, max_size=max_size or MAX_SIZE)
        ctx._store = store
    return ctx
