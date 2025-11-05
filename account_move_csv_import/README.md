# Account Move Import

This Odoo module handle the import of one or several journal entries from a file
(XLSX, XLS, ODS, CSV, TXT or any other format). The name of this module
is account_move_csv_import, but it is not limited to the import of CSV files
(this is an historic name and I didn't want to change it).

This module currently supports:

* XLSX files,
* XLS files,
* ODS files (Libreoffice Calc),
* CSV files,
* FEC (text format),
* Quadratus files.

This module can easily be extended to support other formats. This module supports journal items reconciliation (used for FEC import).

To install this module, you need to install some additional python libraries:

* **openpyxl** (required, needed to support XLSX)
* **xlrd** (required, needed to support XLS)
* **odsparsator** (optional, needed to support ODS)

To install these libraries, run the following commands:

~~~~

pip install --upgrade openpyxl
pip install --upgrade xlrd

~~~~

There are many community modules that handle the import of journal entries
via XLSX/CSV files. But I decided to develop this module because I wanted a module with
the following design guidelines:

* code is easy to read,
* code is easy to debug,
* fast implementation of additionnal formats,
* expressive error messages.

This module is fully configurable. To configure the import formats, go to the menu *Accounting > Configuration > Accounting > Journal Entries Import Configurations*.

For XLSX/XLS/ODS import, you can configure:

* sheet number
* line number to start from
* position of each column

For CSV format, you can configure:

* line number to start from
* position of each column
* encoding
* field delimiter
* date format
* decimal separator
* quoting

For all formats, you can :

* Force a journal
* Automatically post the journal entries and reconcile
* Force the journal entry reference
* Force the journal item label

In addition, several advanced parameters are available, cf the section *Advanced Configuration* of the *Journal Entries Import Configurations*.

This module has been written by Alexis de Lattre from [Akretion France](https://akretion.com/) (alexis.delattre@akretion.com).
