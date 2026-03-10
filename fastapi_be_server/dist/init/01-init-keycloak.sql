-- Keycloak database initialization
CREATE DATABASE IF NOT EXISTS keycloak CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- In local environments, DB_USER_ID may be ln-admin or ln_root.
-- Grant Keycloak DB privileges to both accounts to avoid startup failures.
GRANT ALL PRIVILEGES ON keycloak.* TO 'ln-admin'@'%';
GRANT ALL PRIVILEGES ON keycloak.* TO 'ln_root'@'%';
FLUSH PRIVILEGES;
