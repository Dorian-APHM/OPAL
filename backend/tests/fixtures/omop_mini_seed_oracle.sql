-- Oracle port of omop_mini_seed.sql — the mini-OMOP used by the multi-engine
-- integration harness (tests/test_integration_omop.py) to validate the Oracle
-- dialect against a real instance.
--
-- Run as the schema OWNER (Oracle schema == user). With the official
-- container-registry.oracle.com/database/free image:
--
--   1. create the owner once, as SYSTEM on the FREEPDB1 PDB:
--        ALTER SESSION SET "_ORACLE_SCRIPT"=true;
--        CREATE USER omop_cdm IDENTIFIED BY <pwd>;
--        GRANT CREATE SESSION, CREATE TABLE, UNLIMITED TABLESPACE TO omop_cdm;
--   2. load this file as that user:
--        sqlplus omop_cdm/<pwd>@<host>:1521/FREEPDB1 @omop_mini_seed_oracle.sql
--   3. run (host must be a non-loopback IP — the API blocks loopback for SSRF):
--        OPAL_ITEST_OMOP_HOST=<host> OPAL_ITEST_OMOP_PORT=1521 \
--        OPAL_ITEST_OMOP_DB=FREEPDB1 OPAL_ITEST_OMOP_USER=omop_cdm \
--        OPAL_ITEST_OMOP_PASSWORD=<pwd> OPAL_ITEST_OMOP_SCHEMA=omop_cdm \
--        OPAL_ITEST_OMOP_DBTYPE=oracle \
--        pytest tests/test_integration_omop.py -v
--
-- Same concepts/data as the PostgreSQL seed (320128/201826/1503297/3004249).
-- Differences vs PostgreSQL: NUMBER/VARCHAR2 types, DATE 'yyyy-mm-dd' literals,
-- one-row-per-INSERT (Oracle has no multi-row VALUES), no unaccent extension.

CREATE TABLE concept (
  concept_id NUMBER(19) PRIMARY KEY,
  concept_name VARCHAR2(4000),
  concept_code VARCHAR2(4000),
  domain_id VARCHAR2(4000),
  vocabulary_id VARCHAR2(4000),
  concept_class_id VARCHAR2(4000),
  standard_concept VARCHAR2(4000),
  valid_start_date DATE DEFAULT DATE '2000-01-01',
  valid_end_date DATE DEFAULT DATE '2099-12-31',
  invalid_reason VARCHAR2(4000)
);
INSERT INTO concept(concept_id,concept_name,concept_code,domain_id,vocabulary_id,concept_class_id,standard_concept) VALUES (320128,'Essential hypertension','59621000','Condition','SNOMED','Clinical Finding','S');
INSERT INTO concept(concept_id,concept_name,concept_code,domain_id,vocabulary_id,concept_class_id,standard_concept) VALUES (201826,'Type 2 diabetes mellitus','44054006','Condition','SNOMED','Clinical Finding','S');
INSERT INTO concept(concept_id,concept_name,concept_code,domain_id,vocabulary_id,concept_class_id,standard_concept) VALUES (1503297,'Metformin','6809','Drug','RxNorm','Ingredient','S');
INSERT INTO concept(concept_id,concept_name,concept_code,domain_id,vocabulary_id,concept_class_id,standard_concept) VALUES (3004249,'Systolic blood pressure','8480-6','Measurement','LOINC','Clinical Observation','S');
INSERT INTO concept(concept_id,concept_name,concept_code,domain_id,vocabulary_id,concept_class_id,standard_concept) VALUES (0,'No matching concept',NULL,NULL,NULL,NULL,NULL);
INSERT INTO concept(concept_id,concept_name,concept_code,domain_id,vocabulary_id,concept_class_id,standard_concept) VALUES (21600744,'BLOOD GLUCOSE LOWERING DRUGS','A10','Drug','ATC','ATC 2nd','C');

CREATE TABLE concept_relationship (
  concept_id_1 NUMBER(19), concept_id_2 NUMBER(19), relationship_id VARCHAR2(4000),
  valid_start_date DATE DEFAULT DATE '2000-01-01', valid_end_date DATE DEFAULT DATE '2099-12-31', invalid_reason VARCHAR2(4000)
);
INSERT INTO concept_relationship(concept_id_1,concept_id_2,relationship_id) VALUES (320128,201826,'Maps to');

CREATE TABLE concept_ancestor (
  ancestor_concept_id NUMBER(19), descendant_concept_id NUMBER(19),
  min_levels_of_separation NUMBER(10), max_levels_of_separation NUMBER(10)
);
INSERT INTO concept_ancestor VALUES (21600744,1503297,1,1);
INSERT INTO concept_ancestor VALUES (1503297,1503297,0,0);
INSERT INTO concept_ancestor VALUES (21600744,21600744,0,0);

CREATE TABLE concept_synonym (
  concept_id NUMBER(19), concept_synonym_name VARCHAR2(4000), language_concept_id NUMBER(19) DEFAULT 4180186
);
INSERT INTO concept_synonym(concept_id,concept_synonym_name) VALUES (320128,'High blood pressure');

CREATE TABLE vocabulary (vocabulary_id VARCHAR2(4000) PRIMARY KEY, vocabulary_name VARCHAR2(4000),
  vocabulary_reference VARCHAR2(4000), vocabulary_version VARCHAR2(4000), vocabulary_concept_id NUMBER(19));
INSERT INTO vocabulary(vocabulary_id, vocabulary_name, vocabulary_concept_id)
  SELECT DISTINCT vocabulary_id, vocabulary_id, 0 FROM concept WHERE vocabulary_id IS NOT NULL;

CREATE TABLE person (person_id NUMBER(19) PRIMARY KEY, gender_concept_id NUMBER(19),
  year_of_birth NUMBER(10), month_of_birth NUMBER(10), day_of_birth NUMBER(10),
  race_concept_id NUMBER(19), ethnicity_concept_id NUMBER(19));
INSERT INTO person VALUES (1,8507,1970,3,15,0,0);
INSERT INTO person VALUES (2,8532,1985,7,1,0,0);
INSERT INTO person VALUES (3,8507,1990,11,20,0,0);

CREATE TABLE observation_period (
  observation_period_id NUMBER(19) PRIMARY KEY, person_id NUMBER(19),
  observation_period_start_date DATE, observation_period_end_date DATE, period_type_concept_id NUMBER(19)
);
INSERT INTO observation_period VALUES (1,1,DATE '2015-01-01',DATE '2023-12-31',0);
INSERT INTO observation_period VALUES (2,2,DATE '2016-01-01',DATE '2023-12-31',0);
INSERT INTO observation_period VALUES (3,3,DATE '2017-01-01',DATE '2023-12-31',0);

CREATE TABLE condition_occurrence (
  condition_occurrence_id NUMBER(19) PRIMARY KEY, person_id NUMBER(19),
  condition_concept_id NUMBER(19), condition_start_date DATE, condition_end_date DATE,
  visit_occurrence_id NUMBER(19), condition_source_value VARCHAR2(4000), condition_source_concept_id NUMBER(19)
);
INSERT INTO condition_occurrence VALUES (1,1,320128,DATE '2020-01-05',DATE '2020-01-20',10,'I10',0);
INSERT INTO condition_occurrence VALUES (2,2,320128,DATE '2020-02-10',DATE '2020-02-20',20,'I10',0);
INSERT INTO condition_occurrence VALUES (3,3,0,DATE '2021-03-01',DATE '2021-03-10',30,'E11',0);
INSERT INTO condition_occurrence VALUES (4,1,201826,DATE '2021-06-01',DATE '2021-06-15',11,'E11.9',0);

CREATE TABLE drug_exposure (
  drug_exposure_id NUMBER(19) PRIMARY KEY, person_id NUMBER(19),
  drug_concept_id NUMBER(19), drug_exposure_start_date DATE, drug_exposure_end_date DATE,
  visit_occurrence_id NUMBER(19), drug_source_value VARCHAR2(4000), drug_source_name VARCHAR2(4000),
  drug_source_atc VARCHAR2(4000), drug_source_concept_id NUMBER(19)
);
INSERT INTO drug_exposure VALUES (1,1,1503297,DATE '2020-01-10',DATE '2020-02-10',10,'3679884','METFORMINE 500MG','A10BA02',0);
INSERT INTO drug_exposure VALUES (2,2,1503297,DATE '2020-05-10',DATE '2020-06-10',20,'3679884','METFORMINE 500MG','A10BA02',0);
INSERT INTO drug_exposure VALUES (3,3,0,DATE '2021-01-10',DATE '2021-02-10',30,'9999','PRODUIT INCONNU','Z99ZZ99',0);

CREATE TABLE measurement (
  measurement_id NUMBER(19) PRIMARY KEY, person_id NUMBER(19),
  measurement_concept_id NUMBER(19), measurement_date DATE,
  visit_occurrence_id NUMBER(19), measurement_source_value VARCHAR2(4000), measurement_source_name VARCHAR2(4000),
  measurement_source_concept_id NUMBER(19), value_as_number BINARY_DOUBLE
);
INSERT INTO measurement VALUES (1,1,3004249,DATE '2020-01-05',10,'SYS','Systolic BP',0,140.0);
INSERT INTO measurement VALUES (2,2,3004249,DATE '2020-02-10',20,'SYS','Systolic BP',0,130.0);

-- Remaining OMOP clinical domain tables (empty) so cross-domain UNION queries
-- (e.g. /counts) reference existing relations on this mini-CDM.
CREATE TABLE observation (observation_id NUMBER(19) PRIMARY KEY, person_id NUMBER(19),
  observation_concept_id NUMBER(19), observation_date DATE,
  observation_source_value VARCHAR2(4000), observation_source_concept_id NUMBER(19));
CREATE TABLE procedure_occurrence (procedure_occurrence_id NUMBER(19) PRIMARY KEY, person_id NUMBER(19),
  procedure_concept_id NUMBER(19), procedure_date DATE,
  procedure_source_value VARCHAR2(4000), procedure_source_concept_id NUMBER(19));
CREATE TABLE visit_occurrence (visit_occurrence_id NUMBER(19) PRIMARY KEY, person_id NUMBER(19),
  visit_concept_id NUMBER(19), visit_start_date DATE,
  visit_source_value VARCHAR2(4000), visit_source_concept_id NUMBER(19));
CREATE TABLE device_exposure (device_exposure_id NUMBER(19) PRIMARY KEY, person_id NUMBER(19),
  device_concept_id NUMBER(19), device_exposure_start_date DATE,
  device_source_value VARCHAR2(4000), device_source_concept_id NUMBER(19));
CREATE TABLE death (person_id NUMBER(19) PRIMARY KEY, death_date DATE,
  cause_concept_id NUMBER(19), cause_source_value VARCHAR2(4000), cause_source_concept_id NUMBER(19));
CREATE TABLE specimen (specimen_id NUMBER(19) PRIMARY KEY, person_id NUMBER(19),
  specimen_concept_id NUMBER(19), specimen_date DATE,
  specimen_source_value VARCHAR2(4000), specimen_source_concept_id NUMBER(19));
CREATE TABLE note (note_id NUMBER(19) PRIMARY KEY, person_id NUMBER(19),
  note_type_concept_id NUMBER(19), note_date DATE);
CREATE TABLE payer_plan_period (payer_plan_period_id NUMBER(19) PRIMARY KEY, person_id NUMBER(19),
  payer_concept_id NUMBER(19), payer_plan_period_start_date DATE,
  payer_source_value VARCHAR2(4000), payer_source_concept_id NUMBER(19));

COMMIT;
