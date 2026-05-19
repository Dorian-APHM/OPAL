library(Achilles)

DB_SYSTEM <- Sys.getenv("DB_SYSTEM")
DB_HOST <- Sys.getenv("DB_HOST")
DB_PORT <- Sys.getenv("DB_PORT")
DB_NAME <- Sys.getenv("DB_NAME")
DB_USER <- Sys.getenv("DB_USER")
DB_PASSWORD <- Sys.getenv("DB_PASSWORD")
CDM_SCHEMA <- Sys.getenv("CDM_SCHEMA")
RESULTS_SCHEMA <- Sys.getenv("RESULTS_SCHEMA")
VOCABULARY_SCHEMA <- Sys.getenv("VOCABULARY_SCHEMA")
CDM_SOURCE_NAME <- Sys.getenv("CDM_SOURCE_NAME")
CDM_VERSION <- Sys.getenv("CDM_VERSION")
SERVER <- paste(DB_HOST, "/", DB_NAME, sep="")
PATH_TO_DRIVER <- Sys.getenv("PATH_TO_DRIVER")

connectionDetails <- createConnectionDetails(
    pathToDriver= PATH_TO_DRIVER,
    dbms = DB_SYSTEM,
    server = SERVER,
    port = DB_PORT,
    user = DB_USER,
    password = DB_PASSWORD)

details = getAnalysisDetails()

# By default, we exclude the range of analyses matching cost and payer-plan analyses and exclude 1824 analysis which fills up the disk
ANALYSIS_IDS <- details$analysis_id[!(details$analysis_id >= 1400 & details$analysis_id < 1800)]
# If you've excluded some analyses and you now want to run them:
# - select a subset of analyses (see below) ;
# - set `createTable` to `FALSE` when calling `achilles()`; and
# - set `updateGivenAnalysesOnly` to `TRUE` when calling `achilles()`.

# To only run a single analysis
# ANALYSIS_IDS = details[!(details$ANALYSIS_ID == 1824), "ANALYSIS_ID"]

# To run multiple analyses
# ANALYSIS_IDS = details[ (details$ANALYSIS_ID == 42)
#                        |(details$ANALYSIS_ID == 1824),
#                        "ANALYSIS_ID"]

# https://github.com/OHDSI/Achilles/blob/main/inst/csv/achilles/achilles_analysis_details.csv To see analysis
EXCLUDED_ANALYSIS_IDS = c(
    1824,#blablabla
    2004 #blablabla
    )

achilles(
    connectionDetails,
    cdmVersion = CDM_VERSION,
    cdmDatabaseSchema = CDM_SCHEMA,
    resultsDatabaseSchema = RESULTS_SCHEMA,
    vocabDatabaseSchema = VOCABULARY_SCHEMA,
    tempAchillesPrefix = "tmpach",
    sqlDialect = NULL,

    verboseMode = TRUE,
    numThreads = 1,
    smallCellCount = 0,  # `0` to stop dropping persons with a small number of records (i.e. a test database)
    optimizeAtlasCache = FALSE,

    sqlOnly = FALSE,  # `TRUE` to debug without actually running the queries
    createIndices = TRUE,
    createTable = TRUE,  # `TRUE` will cause the table to be dropped. Set to `FALSE` to merge the analyses results.
    updateGivenAnalysesOnly = FALSE,  # Set to `TRUE` to merge analyses results to the existing results
    dropScratchTables = TRUE,

    defaultAnalysesOnly = TRUE,
    analysisIds = ANALYSIS_IDS,
    excludeAnalysisIds = EXCLUDED_ANALYSIS_IDS,

    sourceName = CDM_SOURCE_NAME,  # Optional, defaults to the value in `cdm_source`
    outputFolder = "output")
