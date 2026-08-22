"""SQLAlchemy 2.0 models -- the single source of truth for the schema.

Every constraint, index and generated column is declared here so that
`alembic revision --autogenerate` produces the migration. Only two things are
hand-written in the initial migration because Alembic cannot generate them:

  1. CREATE EXTENSION pgcrypto   (for gen_random_uuid())
  2. the append-only trigger on ledger_entries

Money is Numeric(14, 2) throughout: exact, sums exactly, and no minor-unit
conversion code anywhere. Every timestamp is DateTime(timezone=True) because
"today's sales" in Asia/Kolkata is not the UTC day.

Enums are Text + CheckConstraint rather than native PG enums -- altering a
Postgres enum is a migration nobody wants to run at 3am.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ---- shared column factories ---------------------------------------------
# Each call builds a fresh MappedColumn; they are never shared between models.

MONEY = Numeric(14, 2)


class Base(DeclarativeBase):
    pass


def _pk():
    return mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _fk(target: str, *, ondelete: str | None = None, nullable: bool = False):
    return mapped_column(
        PgUUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable
    )


def _now():
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ---- the owner / the shop -------------------------------------------------
class Store(Base):
    """One row per shop. The owner's details live here: one owner per store, so
    there is no separate users table until a shop has a second person taking
    khata. `timezone` is not decoration -- every analytics period boundary is
    computed in it."""

    __tablename__ = "stores"

    id: Mapped[UUID] = _pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    owner_name: Mapped[str] = mapped_column(Text, nullable=False)
    owner_mobile: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # E.164
    owner_language: Mapped[str] = mapped_column(
        Text, nullable=False, default="hi-IN", server_default="hi-IN"
    )
    currency: Mapped[str] = mapped_column(
        Text, nullable=False, default="INR", server_default="INR"
    )
    timezone: Mapped[str] = mapped_column(
        Text, nullable=False, default="Asia/Kolkata", server_default="Asia/Kolkata"
    )
    api_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now()

    voiceprints: Mapped[list[SpeakerProfile]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )
    customers: Mapped[list[Customer]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )


# ---- voiceprints: the owner, plus customers who opted in ------------------
EMBEDDING_DIM = 192  # ECAPA-TDNN output


class SpeakerProfile(Base):
    """One row per enrolled voice. `customer_id IS NULL` means the owner.

    N rows per store, so identifying a customer genuinely IS a
    nearest-neighbour search -- which is what pgvector is for. Vector(192) also
    rejects a wrong-sized embedding at write time; the previous LargeBinary
    column accepted any byte string and would have scored every comparison
    against a mismatched model as garbage, silently and forever.

    Two stages use this table, and only the first has authority:

      1. ROLE   -- compare against this store's owner row. Decides
                   owner-vs-customer, which decides whether an utterance can
                   reach a tool at all. This is the security boundary.
      2. IDENTITY -- nearest opted-in customer profile within this store. A
                   SUGGESTION only. mobile+name stays the identity of record and
                   the confirmation gate speaks the name back before money moves,
                   because a misidentification would otherwise put a debt on the
                   wrong person's khata.
    """

    __tablename__ = "speaker_profiles"
    __table_args__ = (
        CheckConstraint("label IN ('owner','customer')", name="ck_profile_label"),
        # Exactly one owner profile per store.
        Index(
            "uq_owner_per_store",
            "store_id",
            unique=True,
            postgresql_where=text("customer_id IS NULL"),
        ),
        # At most one profile per customer.
        UniqueConstraint("store_id", "customer_id", name="uq_profile_per_customer"),
        # A customer voiceprint is third-party biometric data and may only exist
        # WITH recorded consent. Enforced here rather than in a code path that
        # can be forgotten or bypassed by a script.
        CheckConstraint(
            "customer_id IS NULL OR consent_at IS NOT NULL",
            name="ck_customer_profile_needs_consent",
        ),
        Index("ix_profiles_store", "store_id"),
        # HNSW for when a store holds thousands of profiles. At shop scale the
        # planner will prefer ix_profiles_store plus exact distance, and that is
        # correct -- measured 0.014 ms over 500 vectors.
        Index(
            "ix_profiles_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[UUID] = _pk()
    store_id: Mapped[UUID] = _fk("stores.id", ondelete="CASCADE")
    # NULL = the owner of this store. Set = that customer.
    customer_id: Mapped[UUID | None] = _fk(
        "customers.id", ondelete="CASCADE", nullable=True
    )
    label: Mapped[str] = mapped_column(
        Text, nullable=False, default="owner", server_default="owner"
    )
    # 192 dims, unit-normalised at enrolment so cosine distance is 1 - dot.
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=False
    )
    sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    # Per-row, not global: a loud sweet shop and a quiet pharmacy do not share a
    # decision boundary, and the owner's ROUTING threshold should be stricter
    # than a customer SUGGESTION threshold. Calibrate both against real clips.
    threshold: Mapped[float] = mapped_column(
        REAL, nullable=False, default=0.70, server_default=text("0.70")
    )
    # Consent provenance. Required for customer rows; NULL for the owner, since
    # the owner enrolling their own voice is not third-party biometric data.
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_source: Mapped[str | None] = mapped_column(Text)  # 'verbal' | 'app'
    updated_at: Mapped[datetime] = _now()

    store: Mapped[Store] = relationship(back_populates="voiceprints")
# ponytail: no separate consent audit table -- consent_at + consent_source on the
# row IS the record. Add history only if consent-withdrawal history is required.


# ---- the customer ---------------------------------------------------------
class Customer(Base):
    """Mobile and name are mandatory in three places: Pydantic (fast feedback),
    NOT NULL, and a CHECK. A prompt asking the model nicely is not a
    constraint. Uniqueness is scoped to the store, not global -- the same
    person legitimately shops at two stores."""

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("store_id", "mobile", name="uq_customer_store_mobile"),
        CheckConstraint(r"mobile ~ '^\+[1-9][0-9]{7,14}$'", name="ck_mobile_e164"),
        CheckConstraint("btrim(name) <> ''", name="ck_name_nonblank"),
        CheckConstraint(
            r"email IS NULL OR email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'",
            name="ck_email_shape",
        ),
        CheckConstraint(
            "NOT notify_email OR email IS NOT NULL", name="ck_notify_needs_email"
        ),
        Index("ix_customers_store_name", "store_id", text("lower(name)")),
    )

    id: Mapped[UUID] = _pk()
    store_id: Mapped[UUID] = _fk("stores.id", ondelete="CASCADE")
    mobile: Mapped[str] = mapped_column(Text, nullable=False)  # MANDATORY
    name: Mapped[str] = mapped_column(Text, nullable=False)  # MANDATORY
    email: Mapped[str | None] = mapped_column(Text)  # optional: notifications only
    language: Mapped[str | None] = mapped_column(Text)  # BCP-47, for the bridge
    notify_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = _now()

    store: Mapped[Store] = relationship(back_populates="customers")
    entries: Mapped[list[LedgerEntry]] = relationship(back_populates="customer")


# ---- voice provenance ----------------------------------------------------
class VoiceUtterance(Base):
    """One row per detected utterance. Every money row links back to one of
    these, so a khata dispute is settled by replaying the audio that created
    the entry rather than by argument."""

    __tablename__ = "voice_utterances"
    __table_args__ = (
        CheckConstraint(
            "speaker_role IN ('owner','customer','unknown')", name="ck_speaker_role"
        ),
    )

    id: Mapped[UUID] = _pk()
    store_id: Mapped[UUID] = _fk("stores.id", ondelete="CASCADE")
    conversation_id: Mapped[UUID | None] = _fk("conversations.id", nullable=True)
    speaker_role: Mapped[str] = mapped_column(Text, nullable=False)
    speaker_score: Mapped[float | None] = mapped_column(REAL)  # cosine vs voiceprint
    audio_uri: Mapped[str] = mapped_column(Text, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    detected_language: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    transcript_confidence: Mapped[float | None] = mapped_column(REAL)
    stt_provider: Mapped[str] = mapped_column(
        Text, nullable=False, default="sarvam", server_default="sarvam"
    )
    created_at: Mapped[datetime] = _now()


# ---- conversations & messages --------------------------------------------
class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("mode IN ('agent','bridge')", name="ck_conv_mode"),
    )

    id: Mapped[UUID] = _pk()
    store_id: Mapped[UUID] = _fk("stores.id", ondelete="CASCADE")
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[UUID | None] = _fk("customers.id", nullable=True)
    started_at: Mapped[datetime] = _now()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.seq",
    )


class Message(Base):
    """Both the agent's memory and the conversation audit log -- one table
    doing a job we needed done twice.

    `content` holds the raw chat-completions message dict, so load_history()
    replays it byte-exact into the next LLM call. Bridge translations live here
    too rather than in their own table: the bridge IS a conversation.
    """

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_message_conv_seq"),
        CheckConstraint(
            "role IN ('owner','customer','agent','tool')", name="ck_msg_role"
        ),
        CheckConstraint(
            "api_role IS NULL OR api_role IN ('system','user','assistant','tool')",
            name="ck_msg_api_role",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[UUID] = _fk("conversations.id", ondelete="CASCADE")
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    api_role: Mapped[str | None] = mapped_column(Text)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    text_original: Mapped[str | None] = mapped_column(Text)
    lang_original: Mapped[str | None] = mapped_column(Text)
    text_translated: Mapped[str | None] = mapped_column(Text)  # bridge output
    lang_translated: Mapped[str | None] = mapped_column(Text)
    utterance_id: Mapped[UUID | None] = _fk("voice_utterances.id", nullable=True)
    created_at: Mapped[datetime] = _now()

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


# ---- sales (the "transactions") ------------------------------------------
class Sale(Base):
    __tablename__ = "sales"
    __table_args__ = (
        UniqueConstraint("store_id", "request_id", name="uq_sale_idempotency"),
        CheckConstraint("total >= 0", name="ck_sale_total_nonneg"),
        CheckConstraint(
            "payment_mode IN ('cash','upi','card','khata')", name="ck_payment_mode"
        ),
        CheckConstraint(
            "payment_mode <> 'khata' OR customer_id IS NOT NULL",
            name="ck_khata_needs_customer",
        ),
        Index("ix_sales_store_time", "store_id", text("occurred_at DESC")),
    )

    id: Mapped[UUID] = _pk()
    store_id: Mapped[UUID] = _fk("stores.id", ondelete="CASCADE")
    customer_id: Mapped[UUID | None] = _fk("customers.id", nullable=True)  # NULL=walk-in
    total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    payment_mode: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = _now()
    note: Mapped[str | None] = mapped_column(Text)
    utterance_id: Mapped[UUID | None] = _fk("voice_utterances.id", nullable=True)
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now()

    items: Mapped[list[SaleItem]] = relationship(
        back_populates="sale", cascade="all, delete-orphan"
    )


class SaleItem(Base):
    """ponytail: item names are free text, no product master. Add a products
    table when the owner asks for stock levels -- top-selling-item insights
    work fine on lower(item_name)."""

    __tablename__ = "sale_items"
    __table_args__ = (Index("ix_sale_items_name", text("lower(item_name)")),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sale_id: Mapped[UUID] = _fk("sales.id", ondelete="CASCADE")
    item_name: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[Decimal] = mapped_column(
        Numeric(10, 3), nullable=False, default=1, server_default=text("1")
    )
    unit: Mapped[str | None] = mapped_column(Text)  # 'kg' | 'pc' | 'ltr'
    unit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(
        MONEY, Computed("qty * unit_price", persisted=True)
    )

    sale: Mapped[Sale] = relationship(back_populates="items")


# ---- the khata ledger -- APPEND ONLY ------------------------------------
class LedgerEntry(Base):
    """The khata. Never UPDATE, never DELETE -- a correction is a NEW row with
    `reverses_id` set. The append-only trigger enforces that in the database so
    no future refactor, admin script or psql session can quietly rewrite
    someone's debt. This table IS the audit log.

    `signed_amount` is a STORED generated column so a balance is one SUM and
    the sign convention can never drift between the writer and the reader.
    """

    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("store_id", "request_id", name="uq_ledger_idempotency"),
        CheckConstraint("amount > 0", name="ck_amount_positive"),
        CheckConstraint("direction IN (1, -1)", name="ck_direction"),
        CheckConstraint(
            "entry_type IN ('credit_given','payment_received','adjustment','reversal')",
            name="ck_entry_type",
        ),
        CheckConstraint(
            "created_via IN ('voice','text','api')", name="ck_created_via"
        ),
        Index(
            "ix_ledger_cust_time",
            "store_id",
            "customer_id",
            text("occurred_at DESC"),
        ),
    )

    id: Mapped[UUID] = _pk()
    store_id: Mapped[UUID] = _fk("stores.id", ondelete="CASCADE")
    customer_id: Mapped[UUID] = _fk("customers.id")
    entry_type: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # +1 = customer owes more (credit given) | -1 = owes less (payment received)
    direction: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    signed_amount: Mapped[Decimal] = mapped_column(
        MONEY, Computed("amount * direction", persisted=True)
    )
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = _now()
    sale_id: Mapped[UUID | None] = _fk("sales.id", nullable=True)  # sale on khata
    utterance_id: Mapped[UUID | None] = _fk("voice_utterances.id", nullable=True)
    created_via: Mapped[str] = mapped_column(Text, nullable=False)
    reverses_id: Mapped[UUID | None] = _fk("ledger_entries.id", nullable=True)
    request_id: Mapped[str] = mapped_column(Text, nullable=False)  # idempotency
    created_at: Mapped[datetime] = _now()

    customer: Mapped[Customer] = relationship(back_populates="entries")


# ---- the confirmation gate ----------------------------------------------
class PendingAction(Base):
    """Nothing touches money until the owner's voice confirms it.

    STT gets numbers wrong -- "teen sau chalis" and "teen hazaar chalis" differ
    by one word and by Rs 2,700 -- so every mutating tool writes one of these
    first and returns a spoken summary for read-back.
    """

    __tablename__ = "pending_actions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('awaiting','confirmed','cancelled','expired')",
            name="ck_pending_status",
        ),
        Index(
            "ix_pending_awaiting",
            "store_id",
            postgresql_where=text("status = 'awaiting'"),
        ),
    )

    id: Mapped[UUID] = _pk()
    store_id: Mapped[UUID] = _fk("stores.id", ondelete="CASCADE")
    conversation_id: Mapped[UUID] = _fk("conversations.id", ondelete="CASCADE")
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    args: Mapped[dict] = mapped_column(JSONB, nullable=False)
    spoken_summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="awaiting", server_default="awaiting"
    )
    result_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = _now()


# ---- notifications ------------------------------------------------------
class Notification(Base):
    """ponytail: Postgres is the queue. The sweeper uses FOR UPDATE SKIP LOCKED
    so it stays correct with multiple uvicorn workers. Move to arq when you
    need real backoff curves."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("channel IN ('email')", name="ck_notif_channel"),
        CheckConstraint(
            "status IN ('queued','sent','failed','skipped_no_email')",
            name="ck_notif_status",
        ),
        Index(
            "ix_notif_queued",
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
    )

    id: Mapped[UUID] = _pk()
    store_id: Mapped[UUID] = _fk("stores.id", ondelete="CASCADE")
    customer_id: Mapped[UUID] = _fk("customers.id")
    channel: Mapped[str] = mapped_column(
        Text, nullable=False, default="email", server_default="email"
    )
    template: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="queued", server_default="queued"
    )
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
