library(DashboardExport)
packageVersion("DashboardExport")

# Exports Achilles results for the DARWIN Database Dashboard.
# Requires Achilles results to exist in RESULTS_SCHEMA (run "achilles" first).

DB_SYSTEM <- Sys.getenv("DB_SYSTEM")
DB_HOST <- Sys.getenv("DB_HOST")
DB_PORT <- Sys.getenv("DB_PORT")
DB_NAME <- Sys.getenv("DB_NAME")
DB_USER <- Sys.getenv("DB_USER")
DB_PASSWORD <- Sys.getenv("DB_PASSWORD")
CDM_SCHEMA <- Sys.getenv("CDM_SCHEMA")
RESULTS_SCHEMA <- Sys.getenv("RESULTS_SCHEMA")
CDM_SOURCE_NAME <- Sys.getenv("CDM_SOURCE_NAME")
CDM_VERSION <- Sys.getenv("CDM_VERSION", "5.4")
SMALL_CELL_COUNT <- as.integer(Sys.getenv("SMALL_CELL_COUNT", "5"))
SERVER <- paste(DB_HOST, "/", DB_NAME, sep="")
PATH_TO_DRIVER <- Sys.getenv("PATH_TO_DRIVER")

OUTPUT_FOLDER <- Sys.getenv("OUTPUT_DIR", "/output")
print(paste(DB_NAME, " ", RESULTS_SCHEMA, " ", CDM_SCHEMA))

connectionDetails <- DatabaseConnector::createConnectionDetails(
    pathToDriver = PATH_TO_DRIVER,
    dbms = DB_SYSTEM,
    server = SERVER,
    port = DB_PORT,
    user = DB_USER,
    password = DB_PASSWORD)

DashboardExport::dashboardExport(
    connectionDetails = connectionDetails,
    cdmDatabaseSchema = CDM_SCHEMA,
    resultsDatabaseSchema = RESULTS_SCHEMA,
    smallCellCount = SMALL_CELL_COUNT,
    outputFolder = OUTPUT_FOLDER,
    databaseId = CDM_SOURCE_NAME,
    cdmVersion = CDM_VERSION
)
