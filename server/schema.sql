CREATE TABLE IF NOT EXISTS asot_users (
    id text PRIMARY KEY,
    username text UNIQUE,
    email text UNIQUE
);
