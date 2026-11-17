-- Plan 66 (LINK-SO-NOTE): after the release, the owner runs this READ-ONLY query on the live AutoCount book
-- for the PO row his next Link PO created. It returns presence and length only, never the note text.
-- Set @DtlKey to the new linked row's DtlKey (the CRM shows it, or take the newest PODTL row of the PO
-- whose FromDocDtlKey is the S/O line). SELECT only: no write, no temp table.
DECLARE @DtlKey INT = 0;  -- <- put the new PO row's DtlKey here

SELECT
    d.DtlKey,
    d.Seq,
    CASE WHEN d.FromDocDtlKey IS NULL OR d.FromDocDtlKey = 0 THEN 'no' ELSE 'yes' END AS linked_to_so,
    CASE
        WHEN d.FurtherDescription IS NULL THEN 'NULL'
        WHEN DATALENGTH(d.FurtherDescription) = 0 THEN 'EMPTY'
        ELSE 'PRESENT'
    END AS note_state,
    DATALENGTH(d.FurtherDescription) AS note_bytes,
    CASE WHEN CAST(d.FurtherDescription AS NVARCHAR(MAX)) LIKE '%S/O:%' THEN 'yes' ELSE 'no' END AS has_so_marker,
    CASE WHEN CAST(d.FurtherDescription AS NVARCHAR(MAX)) LIKE '{\rtf1%' THEN 'yes' ELSE 'no' END AS is_rtf
FROM PODTL AS d
WHERE d.DtlKey = @DtlKey;

-- Pass: linked_to_so = yes, note_state = PRESENT, has_so_marker = yes, is_rtf = yes.
-- Fail: note_state NULL / EMPTY on a row SS linked after the release -> the link PUT's added row did not
-- store the note either; report to crew (no SS-side door left through hapi).
