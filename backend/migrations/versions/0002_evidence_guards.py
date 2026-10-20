"""Database-enforced immutability of frozen evidence and append-only audit.

Frozen evidence items can change only through the controlled redaction operation, which sets the
transaction-local flag `app.allow_redaction = 'on'`, keeps item_hash, and replaces content/salt with a
tombstone. Metadata that is not part of the hash (source_removed_at) may be set for 'Remove from Library'.
Deleting frozen evidence or audit rows requires `app.allow_purge = 'on'` (retention purge, delete-all).

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_evidence_item() RETURNS trigger AS $$
        DECLARE
          is_frozen boolean;
        BEGIN
          SELECT frozen INTO is_frozen FROM evidence_snapshot
            WHERE id = (CASE WHEN TG_OP = 'DELETE' THEN OLD.snapshot_id ELSE NEW.snapshot_id END);
          IF TG_OP = 'DELETE' THEN
            IF coalesce(is_frozen, false) AND coalesce(current_setting('app.allow_purge', true), '') <> 'on' THEN
              RAISE EXCEPTION 'frozen evidence cannot be deleted' USING ERRCODE = 'check_violation';
            END IF;
            RETURN OLD;
          END IF;
          IF NOT coalesce(is_frozen, false) THEN
            RETURN NEW;
          END IF;
          IF NEW.item_hash IS DISTINCT FROM OLD.item_hash
             OR NEW.snapshot_id IS DISTINCT FROM OLD.snapshot_id
             OR NEW.ordinal IS DISTINCT FROM OLD.ordinal
             OR NEW.kind IS DISTINCT FROM OLD.kind
             OR NEW.output_label IS DISTINCT FROM OLD.output_label THEN
            RAISE EXCEPTION 'frozen evidence is immutable' USING ERRCODE = 'check_violation';
          END IF;
          IF NEW.content IS DISTINCT FROM OLD.content
             OR NEW.salt IS DISTINCT FROM OLD.salt
             OR NEW.provenance IS DISTINCT FROM OLD.provenance
             OR NEW.title IS DISTINCT FROM OLD.title
             OR NEW.redacted_at IS DISTINCT FROM OLD.redacted_at THEN
            IF coalesce(current_setting('app.allow_redaction', true), '') <> 'on'
               OR NEW.redacted_at IS NULL OR NEW.salt IS NOT NULL OR OLD.redacted_at IS NOT NULL THEN
              RAISE EXCEPTION 'frozen evidence is immutable (only the redaction operation may erase content)'
                USING ERRCODE = 'check_violation';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_guard_evidence_item
          BEFORE UPDATE OR DELETE ON evidence_item
          FOR EACH ROW EXECUTE FUNCTION guard_evidence_item();

        CREATE OR REPLACE FUNCTION guard_evidence_snapshot() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.frozen AND coalesce(current_setting('app.allow_purge', true), '') <> 'on' THEN
              RAISE EXCEPTION 'frozen snapshot cannot be deleted' USING ERRCODE = 'check_violation';
            END IF;
            RETURN OLD;
          END IF;
          IF OLD.frozen THEN
            IF NOT NEW.frozen OR NEW.snapshot_hash IS DISTINCT FROM OLD.snapshot_hash
               OR NEW.item_count IS DISTINCT FROM OLD.item_count
               OR NEW.decision_id IS DISTINCT FROM OLD.decision_id THEN
              RAISE EXCEPTION 'frozen snapshot is immutable' USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.integrity_status IS DISTINCT FROM OLD.integrity_status THEN
              IF NEW.integrity_status <> 'redacted'
                 OR coalesce(current_setting('app.allow_redaction', true), '') <> 'on' THEN
                RAISE EXCEPTION 'snapshot integrity can only change through redaction' USING ERRCODE = 'check_violation';
              END IF;
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_guard_evidence_snapshot
          BEFORE UPDATE OR DELETE ON evidence_snapshot
          FOR EACH ROW EXECUTE FUNCTION guard_evidence_snapshot();

        CREATE OR REPLACE FUNCTION guard_audit_event() RETURNS trigger AS $$
        BEGIN
          IF coalesce(current_setting('app.allow_purge', true), '') <> 'on' THEN
            RAISE EXCEPTION 'audit events are append-only' USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_guard_audit_event
          BEFORE UPDATE OR DELETE ON audit_event
          FOR EACH ROW EXECUTE FUNCTION guard_audit_event();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_guard_audit_event ON audit_event;
        DROP TRIGGER IF EXISTS trg_guard_evidence_snapshot ON evidence_snapshot;
        DROP TRIGGER IF EXISTS trg_guard_evidence_item ON evidence_item;
        DROP FUNCTION IF EXISTS guard_audit_event();
        DROP FUNCTION IF EXISTS guard_evidence_snapshot();
        DROP FUNCTION IF EXISTS guard_evidence_item();
        """
    )
