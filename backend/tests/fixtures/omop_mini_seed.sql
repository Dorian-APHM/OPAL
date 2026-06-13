DROP SCHEMA IF EXISTS omop_cdm CASCADE;
CREATE SCHEMA omop_cdm;
CREATE EXTENSION IF NOT EXISTS unaccent;
SET search_path TO omop_cdm;

CREATE TABLE concept (
  concept_id BIGINT PRIMARY KEY,
  concept_name TEXT,
  concept_code TEXT,
  domain_id TEXT,
  vocabulary_id TEXT,
  concept_class_id TEXT,
  standard_concept TEXT,
  valid_start_date DATE DEFAULT '2000-01-01',
  valid_end_date DATE DEFAULT '2099-12-31',
  invalid_reason TEXT
);
INSERT INTO concept(concept_id, concept_name, concept_code, domain_id, vocabulary_id, concept_class_id, standard_concept) VALUES
 (320128,'Essential hypertension','59621000','Condition','SNOMED','Clinical Finding','S'),
 (201826,'Type 2 diabetes mellitus','44054006','Condition','SNOMED','Clinical Finding','S'),
 (1503297,'Metformin','6809','Drug','RxNorm','Ingredient','S'),
 (3004249,'Systolic blood pressure','8480-6','Measurement','LOINC','Clinical Observation','S'),
 (0,'No matching concept',NULL,NULL,NULL,NULL,NULL);

CREATE TABLE concept_relationship (
  concept_id_1 BIGINT, concept_id_2 BIGINT, relationship_id TEXT,
  valid_start_date DATE DEFAULT '2000-01-01', valid_end_date DATE DEFAULT '2099-12-31', invalid_reason TEXT
);
INSERT INTO concept_relationship VALUES (320128,201826,'Maps to');

CREATE TABLE concept_ancestor (
  ancestor_concept_id BIGINT, descendant_concept_id BIGINT,
  min_levels_of_separation INT, max_levels_of_separation INT
);
-- A drug class above Metformin, for hierarchy navigation tests.
INSERT INTO concept(concept_id, concept_name, concept_code, domain_id, vocabulary_id, concept_class_id, standard_concept) VALUES
 (21600744,'BLOOD GLUCOSE LOWERING DRUGS','A10','Drug','ATC','ATC 2nd','C');
INSERT INTO concept_ancestor VALUES
 (21600744,1503297,1,1),
 (1503297,1503297,0,0),
 (21600744,21600744,0,0);
CREATE TABLE concept_synonym (
  concept_id BIGINT, concept_synonym_name TEXT, language_concept_id BIGINT DEFAULT 4180186
);
INSERT INTO concept_synonym VALUES (320128,'High blood pressure');

CREATE TABLE person (person_id BIGINT PRIMARY KEY, gender_concept_id BIGINT,
  year_of_birth INT, month_of_birth INT, day_of_birth INT,
  race_concept_id BIGINT, ethnicity_concept_id BIGINT);
INSERT INTO person VALUES
 (1,8507,1970,3,15,0,0),
 (2,8532,1985,7,1,0,0),
 (3,8507,1990,11,20,0,0);

CREATE TABLE observation_period (
  observation_period_id BIGINT PRIMARY KEY, person_id BIGINT,
  observation_period_start_date DATE, observation_period_end_date DATE,
  period_type_concept_id BIGINT
);
INSERT INTO observation_period VALUES
 (1,1,'2015-01-01','2023-12-31',0),
 (2,2,'2016-01-01','2023-12-31',0),
 (3,3,'2017-01-01','2023-12-31',0);

CREATE TABLE condition_occurrence (
  condition_occurrence_id BIGINT PRIMARY KEY, person_id BIGINT,
  condition_concept_id BIGINT, condition_start_date DATE, condition_end_date DATE,
  visit_occurrence_id BIGINT,
  condition_source_value TEXT, condition_source_concept_id BIGINT
);
INSERT INTO condition_occurrence VALUES
 (1,1,320128,'2020-01-05','2020-01-20',10,'I10',0),
 (2,2,320128,'2020-02-10','2020-02-20',20,'I10',0),
 (3,3,0,'2021-03-01','2021-03-10',30,'E11',0),
 (4,1,201826,'2021-06-01','2021-06-15',11,'E11.9',0);

CREATE TABLE drug_exposure (
  drug_exposure_id BIGINT PRIMARY KEY, person_id BIGINT,
  drug_concept_id BIGINT, drug_exposure_start_date DATE, drug_exposure_end_date DATE,
  visit_occurrence_id BIGINT,
  drug_source_value TEXT, drug_source_name TEXT, drug_source_atc TEXT,
  drug_source_concept_id BIGINT
);
INSERT INTO drug_exposure VALUES
 (1,1,1503297,'2020-01-10','2020-02-10',10,'3679884','METFORMINE 500MG','A10BA02',0),
 (2,2,1503297,'2020-05-10','2020-06-10',20,'3679884','METFORMINE 500MG','A10BA02',0),
 (3,3,0,'2021-01-10','2021-02-10',30,'9999','PRODUIT INCONNU','Z99ZZ99',0);

CREATE TABLE measurement (
  measurement_id BIGINT PRIMARY KEY, person_id BIGINT,
  measurement_concept_id BIGINT, measurement_date DATE,
  visit_occurrence_id BIGINT,
  measurement_source_value TEXT, measurement_source_name TEXT,
  measurement_source_concept_id BIGINT, value_as_number DOUBLE PRECISION
);
INSERT INTO measurement VALUES
 (1,1,3004249,'2020-01-05',10,'SYS','Systolic BP',0,140.0),
 (2,2,3004249,'2020-02-10',20,'SYS','Systolic BP',0,130.0);

-- Remaining OMOP clinical domain tables (empty) so cross-domain UNION queries
-- (e.g. /counts) reference existing relations on this mini-CDM.
CREATE TABLE observation (observation_id BIGINT PRIMARY KEY, person_id BIGINT,
  observation_concept_id BIGINT, observation_date DATE,
  observation_source_value TEXT, observation_source_concept_id BIGINT);
CREATE TABLE procedure_occurrence (procedure_occurrence_id BIGINT PRIMARY KEY, person_id BIGINT,
  procedure_concept_id BIGINT, procedure_date DATE,
  procedure_source_value TEXT, procedure_source_concept_id BIGINT);
CREATE TABLE visit_occurrence (visit_occurrence_id BIGINT PRIMARY KEY, person_id BIGINT,
  visit_concept_id BIGINT, visit_start_date DATE, visit_end_date DATE,
  visit_source_value TEXT, visit_source_concept_id BIGINT);
INSERT INTO visit_occurrence VALUES
 (10,1,9201,'2020-01-05','2020-01-08','I',0),
 (20,2,9201,'2020-02-10','2020-02-12','I',0),
 (30,3,9202,'2021-03-01','2021-03-01','O',0);
CREATE TABLE device_exposure (device_exposure_id BIGINT PRIMARY KEY, person_id BIGINT,
  device_concept_id BIGINT, device_exposure_start_date DATE,
  device_source_value TEXT, device_source_concept_id BIGINT);
CREATE TABLE death (person_id BIGINT PRIMARY KEY, death_date DATE,
  cause_concept_id BIGINT, cause_source_value TEXT, cause_source_concept_id BIGINT);
CREATE TABLE specimen (specimen_id BIGINT PRIMARY KEY, person_id BIGINT,
  specimen_concept_id BIGINT, specimen_date DATE,
  specimen_source_value TEXT, specimen_source_concept_id BIGINT);
CREATE TABLE note (note_id BIGINT PRIMARY KEY, person_id BIGINT,
  note_type_concept_id BIGINT, note_date DATE);
CREATE TABLE payer_plan_period (payer_plan_period_id BIGINT PRIMARY KEY, person_id BIGINT,
  payer_concept_id BIGINT, payer_plan_period_start_date DATE,
  payer_source_value TEXT, payer_source_concept_id BIGINT);
