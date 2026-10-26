-- Apply once with an administrative migration connection.
-- Existing ownerless filings remain inaccessible until explicitly assigned.
BEGIN;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1;
CREATE TABLE IF NOT EXISTS workspace_documents (
  owner_id text NOT NULL,
  sha256 text NOT NULL,
  payload jsonb NOT NULL,
  version integer NOT NULL DEFAULT 1,
  PRIMARY KEY (owner_id, sha256)
);
ALTER TABLE filings ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE digihub_users ENABLE ROW LEVEL SECURITY;
-- Backend service-role access only. No public policies are created.
REVOKE ALL ON filings, documents, workspace_documents, digihub_users FROM anon, authenticated;
COMMIT;
-- Operator action, after verifying ownership: assign filings.created_by to the
-- lowercase login email, then copy that filing's legacy source into the new table.
-- Do not assign all historic filings to the next person who logs in.
-- INSERT INTO workspace_documents(owner_id,sha256,payload)
-- SELECT DISTINCT f.created_by,d.sha256,
-- jsonb_build_object('sha256',d.sha256,
-- 'nodes', CASE WHEN jsonb_typeof(d.nodes)='string' THEN (d.nodes #>> '{}')::jsonb ELSE d.nodes END,
-- 'headers', CASE WHEN jsonb_typeof(d.headers)='string' THEN (d.headers #>> '{}')::jsonb ELSE d.headers END,
-- 'footers', CASE WHEN jsonb_typeof(d.footers)='string' THEN (d.footers #>> '{}')::jsonb ELSE d.footers END,
-- 'warnings', CASE WHEN jsonb_typeof(d.warnings)='string' THEN (d.warnings #>> '{}')::jsonb ELSE d.warnings END)
-- FROM filings f JOIN documents d ON d.sha256=f.document_sha256
-- WHERE f.created_by IS NOT NULL ON CONFLICT DO NOTHING;
