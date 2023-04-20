-- Add up migration script here
CREATE TABLE IF NOT EXISTS labels
(
    id         INTEGER PRIMARY KEY,
    name       TEXT      NOT NULL UNIQUE,
    content_id INTEGER,
    summary_id INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    FOREIGN KEY (content_id) REFERENCES contents (id),
    FOREIGN KEY (summary_id) REFERENCES summaries (id)
);

CREATE TABLE IF NOT EXISTS content_types
(
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

INSERT INTO content_types (name)
VALUES ('RAW_TEXT'),
       ('URL'),
       ('FILE')
ON CONFLICT (name) DO NOTHING;

CREATE TABLE IF NOT EXISTS summaries_statuses
(
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

INSERT INTO summaries_statuses (name)
VALUES ('REQUESTED'),
       ('FINISHED')
ON CONFLICT (name) DO NOTHING;;

CREATE TABLE IF NOT EXISTS summaries
(
    id         INTEGER PRIMARY KEY,
    content    TEXT      NOT NULL,
    status_id  INTEGER,
    content_id INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    FOREIGN KEY (status_id) REFERENCES summaries_statuses (id),
    FOREIGN KEY (content_id) REFERENCES contents (id)
);

CREATE TABLE IF NOT EXISTS contents
(
    id              INTEGER PRIMARY KEY,
    title           TEXT      NOT NULL,
    content         TEXT,
    url             TEXT,
    file_path       TEXT,
    label_id        INTEGER,
    content_type_id INTEGER,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at      TIMESTAMP,
    FOREIGN KEY (label_id) REFERENCES labels (id),
    FOREIGN KEY (content_type_id) REFERENCES content_types (id)
);
