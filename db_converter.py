#!/usr/bin/env python

"""
Fixes a MySQL dump made with the right format so it can be directly
imported to a new PostgreSQL database.

Dump using:
mysqldump --compatible=postgresql --default-character-set=utf8 -r databasename.mysql -u root databasename
"""

import re
import sys
import os
import time
import subprocess


def parse(input_filename, output_filename):
    "Feed it a file, and it'll output a fixed one"

    # State storage
    if input_filename == "-":
        num_lines = -1
    else:
        num_lines = int(subprocess.check_output(["wc", "-l", input_filename]).strip().split()[0])
    tables = {}
    current_table = None
    creation_lines = []
    foreign_key_lines = []
    sequence_lines = []
    cast_lines = []
    num_inserts = 0
    started = time.time()

    # Open output file and write header. Logging file handle will be stdout
    # unless we're writing output to stdout, in which case NO PROGRESS FOR YOU.
    if output_filename == "-":
        output = sys.stdout
        logging = open(os.devnull, "w")
    else:
        output = open(output_filename, "w")
        logging = sys.stdout

    if input_filename == "-":
        input_fh = sys.stdin
    else:
        input_fh = open(input_filename)


    output.write("-- Converted by db_converter\n")
    output.write("START TRANSACTION;\n")
    output.write("SET standard_conforming_strings=off;\n")
    output.write("SET escape_string_warning=off;\n")
    output.write("SET CONSTRAINTS ALL DEFERRED;\n\n")

    for i, line in enumerate(input_fh):
        time_taken = time.time() - started
        percentage_done = (i+1) / float(num_lines)
        secs_left = (time_taken / percentage_done) - time_taken
        logging.write("\rLine %i (of %s: %.2f%%) [%s tables] [%s inserts] [ETA: %i min %i sec]" % (
            i + 1,
            num_lines,
            ((i+1)/float(num_lines))*100,
            len(tables),
            num_inserts,
            secs_left // 60,
            secs_left % 60,
        ))
        logging.flush()
        line = line.decode("utf8").strip().replace(r"\\", "WUBWUBREALSLASHWUB").replace(r"\'", "''").replace("WUBWUBREALSLASHWUB", r"\\")
        # Ignore comment lines
        if line.startswith("--") or line.startswith("/*") or line.startswith("LOCK TABLES") or line.startswith("DROP TABLE") or line.startswith("UNLOCK TABLES") or not line:
            continue

        # Outside of anything handling
        if current_table is None:
            # Start of a table creation statement?
            if line.startswith("CREATE TABLE"):
                current_table = line.split('"')[1]
                output.write("CREATE TABLE \"%s\" (\n" % current_table)
                tables[current_table] = {"columns": []}
                creation_lines = []
            # Inserting data into a table?
            elif line.startswith("INSERT INTO"):
                output.write(line.encode("utf8").replace("'0000-00-00 00:00:00'", "NULL") + "\n")
                num_inserts += 1
            # ???
            else:
                print "\n ! Unknown line in main body: %s" % line

        # Inside-create-statement handling
        else:
            # Is it a column?
            if line.startswith('"'):
                useless, name, definition = line.strip(",").split('"',2)
                try:
                    type, extra = definition.strip().split(" ", 1)
                except ValueError:
                    type = definition.strip()
                    extra = ""
                extra = re.sub("CHARACTER SET [\w\d]+\s*", "", extra.replace("unsigned", ""))
                # See if it needs type conversion
                final_type = None
                if type == "tinyint(1)":
                    type = "int4"
                    final_type = "boolean"
                elif type.startswith("int("):
                    type = "integer"
                elif type.startswith("bigint("):
                    type = "bigint"
                elif type == "longtext":
                    type = "text"
                elif type == "mediumtext":
                    type = "text"
                elif type == "tinytext":
                    type = "text"
                elif type.startswith("varchar("):
                    size = int(type.split("(")[1].rstrip(")"))
                    type = "varchar(%s)" % (size * 2)
                elif type.startswith("smallint("):
                    type = "int2"
                elif type == "datetime":
                    type = "timestamp with time zone"
                elif type == "double":
                    type = "double precision"
                if final_type:
                    cast_lines.append("ALTER TABLE \"%s\" ALTER COLUMN \"%s\" DROP DEFAULT, ALTER COLUMN \"%s\" TYPE %s USING CAST(\"%s\" as %s)" % (current_table, name, name, final_type, name, final_type))
                # ID fields need sequences
                if name == "id":
                    sequence_lines.append("CREATE SEQUENCE %s_id_seq" % (current_table))
                    sequence_lines.append("SELECT setval('%s_id_seq', max(id)) FROM %s" % (current_table, current_table))
                    sequence_lines.append("ALTER TABLE \"%s\" ALTER COLUMN \"id\" SET DEFAULT nextval('%s_id_seq')" % (current_table, current_table))
                # Record it
                creation_lines.append('"%s" %s %s' % (name, type, extra))
                tables[current_table]['columns'].append((name, type, extra))
            # Is it a constraint or something?
            elif line.startswith("PRIMARY KEY"):
                creation_lines.append(line.rstrip(","))
            elif line.startswith("CONSTRAINT"):
                foreign_key_lines.append("ALTER TABLE \"%s\" ADD CONSTRAINT %s DEFERRABLE INITIALLY DEFERRED" % (current_table, line.split("CONSTRAINT")[1].strip().rstrip(",")))
                foreign_key_lines.append("CREATE INDEX ON \"%s\" %s" % (current_table, line.split("FOREIGN KEY")[1].split("REFERENCES")[0].strip().rstrip(",")))
            elif line.startswith("UNIQUE KEY"):
                creation_lines.append("UNIQUE (%s)" % line.split("(")[1].split(")")[0])
            elif line.startswith("KEY"):
                pass
            # Is it the end of the table?
            elif line == ");":
                for i, line in enumerate(creation_lines):
                    output.write("    %s%s\n" % (line, "," if i != (len(creation_lines) - 1) else ""))
                output.write(');\n\n')
                current_table = None
            # ???
            else:
                print "\n ! Unknown line inside table creation: %s" % line


    # Finish file
    output.write("\n-- Post-data save --\n")
    output.write("COMMIT;\n")
    output.write("START TRANSACTION;\n")

    # Write typecasts out
    output.write("\n-- Typecasts --\n")
    for line in cast_lines:
        output.write("%s;\n" % line)

    # Write FK constraints out
    output.write("\n-- Foreign keys --\n")
    for line in foreign_key_lines:
        output.write("%s;\n" % line)

    # Write sequences out
    output.write("\n-- Sequences --\n")
    for line in sequence_lines:
        output.write("%s;\n" % line)

    # Finish file
    output.write("\n")
    output.write("COMMIT;\n")
    print ""


if __name__ == "__main__":
    parse(sys.argv[1], sys.argv[2])
