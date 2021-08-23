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

# Set this to the default value which should be assigned to MySQL's 0000-00-00 values
# (which are not supported by Postgres)
# For example:
#   * NULL
#   * 1990-01-01
DATE_DEFAULT = "1900-01-01"

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
    enum_types = []
    foreign_key_lines = []
    fulltext_key_lines = []
    sequence_lines = []
    cast_lines = []
    num_inserts = 0
    started = time.time()
    commentRE = re.compile("COMMENT *'(.*)'$")

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
                tables[current_table] = {"columns": []}
                creation_lines = []
                comment_lines = []
            # Inserting data into a table?
            elif line.startswith("INSERT INTO"):
                output.write(re.sub(r"([\(,])'0000-00-00'", r"\1'"+DATE_DEFAULT+"'", re.sub(r"([\(,])'0000-00-00 00:00:00'", r"\1'"+DATE_DEFAULT+"'", line.encode("utf8"))) + "\n")
                num_inserts += 1
            # ???
            else:
                print("\n ! Unknown line in main body: %s" % line)

        # Inside-create-statement handling
        else:
            # Is it a column?
            if line.startswith('"'):
                useless, name, definition = line.strip(",").split('"',2)
                try:
                    type, extra = definition.strip().split(" ", 1)

                    # This must be a tricky enum
                    if ')' in extra:
                        type, extra = definition.strip().split(")")

                except ValueError:
                    type = definition.strip()
                    extra = ""
                commentMatch = commentRE.search(extra)
                if (commentMatch):
                    comment_lines.append((name, commentMatch.group(1)))
                extra = re.sub("COMMENT '(.*)',?$", "", extra.replace("unsigned", ""))
                extra = re.sub("CHARACTER SET [\w\d]+\s*", "", extra.replace("unsigned", ""))
                extra = re.sub("COLLATE [\w\d]+\s*", "", extra.replace("unsigned", ""))

                # See if it needs type conversion
                final_type = None
                set_sequence = None
                if type.startswith("tinyint("):
                    type = "int4"
                    set_sequence = True
                    final_type = "boolean"
                elif type.startswith("int("):
                    type = "integer"
                    set_sequence = True
                elif type.startswith("bigint("):
                    type = "bigint"
                    set_sequence = True
                elif type == "longtext":
                    type = "text"
                elif type == "mediumtext":
                    type = "text"
                elif type == "tinytext":
                    type = "text"
                elif type.startswith("varchar("):
                    size = int(type.split("(")[1].split(")")[0])
                    type = "varchar(%s)" % (size * 2)
                elif type.startswith("smallint("):
                    type = "int2"
                    set_sequence = True
                elif type == "datetime":
                    type = "timestamp with time zone"
                elif type == "double":
                    type = "double precision"
                elif type.endswith("blob"):
                    type = "bytea"
                elif type == "date":
                    type, extra = convert_date(type, extra)
                elif type == "timestamp":
                    type, extra = convert_date(type, extra)
                elif type.startswith("enum(") or type.startswith("set("):

                    types_str = type.split("(")[1].rstrip(")").rstrip('"')
                    types_arr = [type_str.strip('\'') for type_str in types_str.split(",")]

                    # Considered using values to make a name, but its dodgy
                    # enum_name = '_'.join(types_arr)
                    enum_name = "{0}_{1}".format(current_table, name)

                    if enum_name not in enum_types:
                        output.write("DROP TYPE IF EXISTS {0}; \n".format(enum_name));
                        output.write("CREATE TYPE {0} AS ENUM ({1}); \n".format(enum_name, types_str));
                        enum_types.append(enum_name)

                    type = enum_name

                if final_type:
                    cast_lines.append("ALTER TABLE \"%s\" ALTER COLUMN \"%s\" DROP DEFAULT, ALTER COLUMN \"%s\" TYPE %s USING CAST(\"%s\" as %s)" % (current_table, name, name, final_type, name, final_type))
                # ID fields need sequences [if they are integers?]
                if name == "id" and set_sequence is True:
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
            elif line.startswith("FULLTEXT KEY"):

                fulltext_keys = " || ' ' || ".join( line.split('(')[-1].split(')')[0].replace('"', '').split(',') )
                fulltext_key_lines.append("CREATE INDEX ON %s USING gin(to_tsvector('english', %s))" % (current_table, fulltext_keys))

            elif line.startswith("KEY"):
                pass
            # Is it the end of the table?
            elif line == ");":
                output.write("CREATE TABLE \"%s\" (\n" % current_table)
                for i, line in enumerate(creation_lines):
                    output.write("    %s%s\n" % (line.encode("utf8"), "," if i != (len(creation_lines) - 1) else ""))
                output.write(');\n\n')
                # Write sequences out
                output.write("\n-- Comments --\n")
                for line in comment_lines:
                    field, comment = line
                    output.write("COMMENT ON COLUMN \"%s\".\"%s\" IS '%s';\n" % (current_table, field, comment))
                current_table = None
            # ???
            else:
                print("\n ! Unknown line inside table creation: %s" % line)


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

    # Write full-text indexkeyses out
    output.write("\n-- Full Text keys --\n")
    for line in fulltext_key_lines:
        output.write("%s;\n" % line)

    # Finish file
    output.write("\n")
    output.write("COMMIT;\n")
    print("")

def convert_date(type, extra):
    not_null = 'NOT NULL' in extra

    # A default date is given and the schema says, column should be not null,
    # so we replace out-of-range values with default value or 01-01
    if DATE_DEFAULT != 'NULL' and not_null:
        # replace 0000-00-00 by DATE_DEFAULT
        extra = re.sub('DEFAULT \'0000-00-00\'', 'DEFAULT \'%s\'' % DATE_DEFAULT, extra)
        # replace 0000-00-00 by DATE_DEFAULT
        extra = re.sub('DEFAULT \'0000-00-00 00:00:00\'', 'DEFAULT \'%s\'' % DATE_DEFAULT, extra)
        # replace YYYY-00-00 by YYYY-01-01
        extra = re.sub(r"(DEFAULT '\d\d\d\d)-00-00'", r"\1-01-01'", extra)

    # The default date that is given is NULL, the schema says NOT NULL
    # and the default value of the schema is invalid. So we resolve this
    # conflict by making the column nullable
    if DATE_DEFAULT == 'NULL' and not_null and "DEFAULT '0000-00-00'" in extra:
        extra = re.sub('NOT NULL', '', extra)
        extra = re.sub('DEFAULT \'0000-00-00\'', '', extra)

    return type, extra

if __name__ == "__main__":
    parse(sys.argv[1], sys.argv[2])
