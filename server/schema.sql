CREATE TABLE IF NOT EXISTS asot_users (
    user_id text PRIMARY KEY,
    username text UNIQUE,
    email text UNIQUE,
    auth_token text UNIQUE
);
