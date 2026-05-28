library(Achilles)
packageVersion("Achilles")
packageVersion("jsonlite")
#La version 1.7.2 ne fonctionne pas : https://github.com/OHDSI/Achilles/issues/726
#Actuellement j'utilise la 1.7.0

DB_SYSTEM <- Sys.getenv("DB_SYSTEM")
DB_HOST <- Sys.getenv("DB_HOST")
DB_PORT <- Sys.getenv("DB_PORT")
DB_NAME <- Sys.getenv("DB_NAME")
DB_USER <- Sys.getenv("DB_USER")
DB_PASSWORD <- Sys.getenv("DB_PASSWORD")
CDM_SCHEMA <- Sys.getenv("CDM_SCHEMA")
RESULTS_SCHEMA <- Sys.getenv("RESULTS_SCHEMA")
SERVER <- paste(DB_HOST, "/", DB_NAME, sep="")
PATH_TO_DRIVER <- Sys.getenv("PATH_TO_DRIVER")

OUTPUT_FOLDER <- Sys.getenv("OUTPUT_DIR", "/output")
print(paste(DB_NAME," ",RESULTS_SCHEMA," ",CDM_SCHEMA))

connectionDetails <- createConnectionDetails(
    pathToDriver= PATH_TO_DRIVER,
    dbms = DB_SYSTEM,
    server = SERVER,
    port = DB_PORT,
    user = DB_USER,
    password = DB_PASSWORD)

# See <https://forums.ohdsi.org/t/achilles-exportjson-issue-with-postgres/220>.
REPORTS <- c(
    "REPORT",
    "CONDITION",
    "CONDITION_ERA",
    "DASHBOARD",
    "DATA_DENSITY",
    "DEATH",
    "DRUG",
    "DRUG_ERA",
    "OBSERVATION",
    "OBSERVATION_PERIOD",
    "PERFORMANCE",
    "PERSON",
    "PROCEDURE",
    "VISIT",
    "MEASUREMENT",
    "META",
    "VISIT_DETAIL")

exportToJson(
  connectionDetails,
  cdmDatabaseSchema = CDM_SCHEMA,
  resultsDatabaseSchema = RESULTS_SCHEMA,

  compressIntoOneFile = FALSE, # creates gzipped file of all JSON files

  report=REPORTS,

  outputPath = OUTPUT_FOLDER)
