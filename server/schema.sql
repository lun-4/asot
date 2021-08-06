CREATE TABLE IF NOT EXISTS asot_users (
    id text PRIMARY KEY,
    username text UNIQUE NOT NULL,
    email text UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS asot_sessions (
    user_id text PRIMARY KEY REFERENCES asot_users (id),
    session_id text UNIQUE NOT NULL,
    created_at text NOT NULL -- iso timestamp of creation
);
