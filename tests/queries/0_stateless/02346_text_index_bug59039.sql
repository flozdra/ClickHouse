-- Test that DROP INDEX removes all index related files.
-- This can't be tested directly but we can at least check that no bad things happen.

SET allow_experimental_full_text_index = 1;

DROP TABLE IF EXISTS tab;

CREATE TABLE tab
(
    id UInt64,
    doc String,
    INDEX text_idx doc TYPE text(tokenizer = 'default')
)
ENGINE = MergeTree
ORDER BY id
SETTINGS index_granularity = 2, index_granularity_bytes = '10Mi', min_bytes_for_wide_part = 0, min_rows_for_wide_part = 0;

ALTER TABLE tab DROP INDEX text_idx;

DROP TABLE tab;
