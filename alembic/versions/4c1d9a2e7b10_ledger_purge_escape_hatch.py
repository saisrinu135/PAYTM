"""Allow deliberate, session-scoped DELETE on ledger_entries; UPDATE stays banned

The append-only trigger blocked ALL deletes, which turned out to be too broad in
two concrete ways:

  1. Deleting a store cascades to its ledger rows. With the trigger absolute,
     `DELETE FROM stores` fails -- so a store could never be removed, and the
     idempotent seed reset could not run twice.
  2. A data-erasure request ("delete everything you hold about me") is a
     legitimate, deliberate operation. Making it impossible is not a stronger
     guarantee, just a different failure.

So the guard now distinguishes the two things it was conflating:

  * UPDATE  -- still refused unconditionally, no bypass at all. A correction is
              ALWAYS a new reversal row. This is the guarantee that makes the
              khata trustworthy, and nothing may weaken it.
  * DELETE  -- refused by default, permitted only when the transaction has
              explicitly opted in with
                  SET LOCAL app.allow_ledger_purge = 'on'
              SET LOCAL is transaction-scoped, so it cannot leak into another
              statement, and it is greppable: any code that erases ledger rows
              has to say so out loud.

Revision ID: 4c1d9a2e7b10
Revises: 3ab3f683fe23
"""
from collections.abc import Sequence

from alembic import op

revision: str = '4c1d9a2e7b10'
down_revision: str | Sequence[str] | None = '3ab3f683fe23'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ledger_is_append_only() RETURNS trigger AS $$
        BEGIN
          -- UPDATE: never, under any setting. Corrections are reversal rows.
          IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION
              'ledger_entries is append-only; insert a reversal row instead'
              USING ERRCODE = 'restrict_violation';
          END IF;

          -- DELETE: only for a transaction that explicitly opted in.
          IF coalesce(current_setting('app.allow_ledger_purge', true), 'off')
             <> 'on' THEN
            RAISE EXCEPTION
              'ledger_entries is append-only; to erase a store''s data set '
              'app.allow_ledger_purge = ''on'' in this transaction'
              USING ERRCODE = 'restrict_violation';
          END IF;

          RETURN OLD;
        END $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ledger_is_append_only() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION
            'ledger_entries is append-only; insert a reversal row instead'
            USING ERRCODE = 'restrict_violation';
        END $$ LANGUAGE plpgsql;
        """
    )
