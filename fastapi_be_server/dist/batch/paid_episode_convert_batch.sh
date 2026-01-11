#!/bin/bash

DB_HOST="10.0.100.78"
DB_PORT="3306"
DB_USER="ln-admin"
DB_PW="likenovel684233^^"
DB_NAME="likenovel"

mysql -h $DB_HOST -P $DB_PORT -u $DB_USER -p$DB_PW $DB_NAME < /home/ln-admin/likenovel/batch/paid_episode_convert_batch.sql

exit 0
