library(DataQualityDashboard)


DB_SYSTEM <- Sys.getenv("DB_SYSTEM")
DB_HOST <- Sys.getenv("DB_HOST")
DB_PORT <- Sys.getenv("DB_PORT")
DB_NAME <- Sys.getenv("DB_NAME")
DB_USER <- Sys.getenv("DB_USER")
DB_PASSWORD <- Sys.getenv("DB_PASSWORD")
SERVER <- paste(DB_HOST, "/", DB_NAME, sep="")
PATH_TO_DRIVER <- Sys.getenv("PATH_TO_DRIVER")
CDM_VERSION <- Sys.getenv("CDM_VERSION")
CDM_SOURCE_NAME <- Sys.getenv("CDM_SOURCE_NAME")

CDM_SCHEMA <- Sys.getenv("CDM_SCHEMA")
RESULTS_SCHEMA <- Sys.getenv("RESULTS_SCHEMA")
VOCABULARY_SCHEMA <- Sys.getenv("VOCABULARY_SCHEMA")

print(paste(DB_NAME," ",RESULTS_SCHEMA," ",CDM_SCHEMA))

connectionDetails <- createConnectionDetails(pathToDriver= PATH_TO_DRIVER,
                                             dbms = DB_SYSTEM,
                                             server = SERVER,
                                             port = DB_PORT,
                                             user = DB_USER,
                                             password = DB_PASSWORD)

numThreads <- 1 # on Redshift, 3 seems to work well
sqlOnly <- FALSE # set to TRUE if you just want to get the SQL scripts and not actually run the queries
verboseMode <- FALSE # set to TRUE if you want to see activity written to the console
writeToTable <- FALSE # set to FALSE if you want to skip writing to a SQL table in the results schema

checkLevels <- c("TABLE", "FIELD", "CONCEPT") #On peut selectionner ici qu'une partie qu'on veut vérifier
checkNames <- c() # Names can be found in inst/csv/OMOP_CDM_v5.3.1_Check_Desciptions.csv
tablesToExclude <- c()

outputFolder <- "/output"

DataQualityDashboard::executeDqChecks(connectionDetails = connectionDetails,
                                      cdmVersion = CDM_VERSION,
                                      cdmDatabaseSchema = CDM_SCHEMA,
                                      resultsDatabaseSchema = RESULTS_SCHEMA,
                                      vocabDatabaseSchema = VOCABULARY_SCHEMA,
                                      cdmSourceName = CDM_SOURCE_NAME,
                                      numThreads = numThreads,
                                      sqlOnly = sqlOnly,
                                      outputFolder = outputFolder,
                                      writeToTable = writeToTable,
                                      checkLevels = checkLevels,
                                      tablesToExclude = tablesToExclude,
                                      checkNames = checkNames,
                                      conceptCheckThresholdLoc = "scripts/config/OMOP_CDMv5.4_Concept_Level.csv",
                                      tableCheckThresholdLoc = "scripts/config/OMOP_CDMv5.4_Table_Level.csv",
                                      fieldCheckThresholdLoc = "scripts/config/OMOP_CDMv5.4_Field_Level.csv",
                                      verboseMode = verboseMode)
