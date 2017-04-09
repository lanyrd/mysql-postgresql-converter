MySQL to PostgreSQL Converter
=============================

Lanyrd's MySQL to PostgreSQL conversion script. Use with care.

This script was designed for our specific database and column requirements -
notably, it doubles the lengths of VARCHARs due to a unicode size problem we
had, places indexes on all foreign keys, and presumes you're using Django
for column typing purposes.

For a more general approach have a look at pgloader <https://github.com/dimitri/pgloader>, 
which connects to a running MySQL instance and discovers the schema from the catalogs to
then reproduce it in PostgreSQL with a default set of casting rules (that you can edit).
[pgloader](https://github.com/dimitri/pgloader) supports migrating the schema and the data,
converting data on the fly, and reproducing Not Null constraints, default values, primary
and secondary indexes, foreign keys and comments.

How to use
----------

First, dump your MySQL database in PostgreSQL-compatible format

    mysqldump --compatible=postgresql --default-character-set=utf8 \
    -r databasename.mysql -u root databasename

Then, convert it using the dbconverter.py script

`python db_converter.py databasename.mysql databasename.psql`

It'll print progress to the terminal.

Finally, load your new dump into a fresh PostgreSQL database using: 

`psql -f databasename.psql`

More information
----------------

You can learn more about the move which this powered at http://lanyrd.com/blog/2012/lanyrds-big-move/ and some technical details of it at http://www.aeracode.org/2012/11/13/one-change-not-enough/.
