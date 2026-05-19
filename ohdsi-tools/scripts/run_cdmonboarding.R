#' CodeToRun.R
#' 
#' This script provides an example of how to run the CdmOnboarding package.
#' It retrieves connection details from environment variables defeined your .Renviron file:
#' Note that these follow DBI driver settings and might differ per DBMS. For postgres:
#'    DBMS = "postgresql"
#'    DB_HOST = "localhost_or_other_host"
#'    DB_PORT = 5432
#'    DB_NAME = "your_database_name"
#'    DB_USER = "your_user"
#'    DB_PASSWORD = "your_secret_password"
#'    CDM_SCHEMA = "your_cdm_schema"
#'    RESULTS_SCHEMA = "your_achilles_results_schema"
#'
#' Examples for other DBMS: https://darwin-eu.github.io/CDMConnector/articles/a04_DBI_connection_examples.html

# Install latest version of CdmOnboarding if not already installed
if (!require(CdmOnboarding)) {
  remotes::install_github("DARWIN-EU/CdmOnboarding")
}

library(CdmOnboarding)

# Fill out the DBI connection details -----------------------------------------------------------------------
connectionDetails <- DatabaseConnector::createDbiConnectionDetails(
  dbms = "postgresql",
  drv = RPostgres::Postgres(),
  host = Sys.getenv("DB_HOST"),
  port = Sys.getenv("DB_PORT"),
  dbname = Sys.getenv("DB_NAME"),
  user = Sys.getenv("DB_USER"),
  password = Sys.getenv("DB_PASSWORD")
)

# Details for connecting to the CDM
cdmSchema <- Sys.getenv("CDM_SCHEMA")
resultsSchema <- Sys.getenv("RESULTS_SCHEMA")

# Details specific to the database:
databaseId <- "APHM"
authors <- c('Vanessa Pauly', 'Dorian Grousset') # used on the title page

# (optional) URL to the WebAPI that your local Atlas instance uses, e.g. http://localhost:8080/WebAPI
baseUrl <- Sys.getenv("WEBAPI_BASEURL")

# Auto-detect : prend le JSON DQD le plus récent dans /input/dqd/
dqdJsonFiles <- list.files('/input/dqd', pattern = '\\.json$', full.names = TRUE)
if (length(dqdJsonFiles) == 0) {
  stop("Aucun fichier JSON DQD trouvé dans /input/dqd/. Lancez DQD d'abord.")
}
dqdJsonPath <- dqdJsonFiles[which.max(file.info(dqdJsonFiles)$mtime)]
cat("Utilisation du fichier DQD:", dqdJsonPath, "\n")
outputFolder <- '/output'
smallCellCount <- 5
verboseMode <- TRUE

# *******************************************************
# SECTION 3: Run the package
# *******************************************************
results <- CdmOnboarding::cdmOnboarding(
  connectionDetails = connectionDetails,
  cdmSchema = cdmSchema,
  resultsSchema = resultsSchema,
  databaseId = databaseId,
  authors = authors,
  smallCellCount = smallCellCount,
  baseUrl = baseUrl,
  outputFolder = outputFolder,
  dqdJsonPath = dqdJsonPath
)

# cdmOnboarding() should already generate the resultsdocument.
# Use this to regenerate upon error (results object should be returned anyway)
if (FALSE) {
  CdmOnboarding::generateResultsDocument(
    results = results,
    outputFolder = outputFolder,
    authors = authors
  )
}
