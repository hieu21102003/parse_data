-- Table: public.organizations

-- DROP TABLE IF EXISTS public.organizations;

CREATE TABLE IF NOT EXISTS public.organizations
(
    org_id integer NOT NULL DEFAULT nextval('organizations_org_id_seq'::regclass),
    org_code character varying(20) COLLATE pg_catalog."default" NOT NULL,
    org_name text COLLATE pg_catalog."default" NOT NULL,
    country text COLLATE pg_catalog."default",
    CONSTRAINT organizations_pkey PRIMARY KEY (org_id),
    CONSTRAINT organizations_org_code_key UNIQUE (org_code)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.organizations
    OWNER to postgres;

REVOKE ALL ON TABLE public.organizations FROM standards_user;

GRANT ALL ON TABLE public.organizations TO postgres;

GRANT INSERT, DELETE, SELECT, UPDATE ON TABLE public.organizations TO standards_user;

-- 13. standard_series
CREATE TABLE IF NOT EXISTS public.standard_series (
    series_id SERIAL PRIMARY KEY,
    org_prefix VARCHAR(50) NOT NULL,
    series_number VARCHAR(50) NOT NULL,
    series_title TEXT,
    created_at TIMESTAMP DEFAULT now(),

    CONSTRAINT uniq_series UNIQUE (org_prefix, series_number)
);

-- Refactoring existings tables
ALTER TABLE public.standards
ADD COLUMN series_id INTEGER,
ADD COLUMN parent_std_id INTEGER,
ADD COLUMN hierarchy_level INTEGER,
ADD COLUMN std_code_full VARCHAR(100);

-- Foreign Keys
ALTER TABLE public.standards
ADD CONSTRAINT fk_series
FOREIGN KEY (series_id)
REFERENCES public.standard_series(series_id);

ALTER TABLE public.standards
ADD CONSTRAINT fk_parent_std
FOREIGN KEY (parent_std_id)
REFERENCES public.standards(std_id);

-- Unique constraints
DROP INDEX IF EXISTS uniq_standard;

CREATE UNIQUE INDEX uniq_standard_new
ON public.standards (
    org_prefix,
    std_main_number,
    std_part,
    std_year
);

---
ALTER TABLE public.standard_versions
ADD COLUMN amendment VARCHAR(50),
ADD COLUMN version_label VARCHAR(100);

--- 14. Domains
CREATE TABLE domains (
    domain_id SERIAL PRIMARY KEY,
    domain_code VARCHAR(50),
    domain_name TEXT
);

CREATE TABLE standard_domains (
    std_id INTEGER,
    domain_id INTEGER,
    PRIMARY KEY (std_id, domain_id)
);

-- 15. logs
CREATE TABLE parser_logs (
    log_id SERIAL PRIMARY KEY,

    raw_code TEXT,
    normalized_code TEXT,

    std_id INTEGER,

    parser_name VARCHAR(50),
    parser_version VARCHAR(20),

    confidence_score NUMERIC(4,3),
    confidence_breakdown JSONB,

    is_valid BOOLEAN,
    error_message TEXT,

    created_at TIMESTAMP DEFAULT now()
);


-- 17. Org normalization
ALTER TABLE organizations
ADD COLUMN org_normalized VARCHAR(50),
ADD COLUMN confidence_score NUMERIC(3,2),
ADD COLUMN is_verified BOOLEAN DEFAULT FALSE;

CREATE TABLE org_aliases (
    alias_id SERIAL PRIMARY KEY,
    alias_text VARCHAR(100),
    org_id INTEGER,
    confidence NUMERIC(3,2),
    created_at TIMESTAMP DEFAULT now()
);


