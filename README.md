MySQL to PostgreSQL Converter
=============================

Lanyrd's MySQL to PostgreSQL conversion script. Use with care.

This script was designed for our specific database and column requirements -
notably, it doubles the lengths of VARCHARs due to a unicode size problem we
had, places indexes on all foreign keys, and presumes you're using Django
for column typing purposes.

How to use
----------

Firstly, dump your database using `mysqldump --compatible=postgresql --default-character-set=utf8 -r databasename.mysql -u root databasename`.

Then, run the converter script using `python dbconverter.py databasename.mysql databasename.psql` - it'll print
progress to the terminal.

Finally, load your new dump into a fresh PostgreSQL database using `psql -f databasename.psql`.
