API Reference
=============

Repository State
----------------
.. This tells Sphinx to import Hallmark modules and extract their
   module and function docstrings.

.. automodule:: hallmark.repo
   :members:

.. automodule:: hallmark.repo_state
   :members:

.. automodule:: hallmark.state
   :members:

.. automodule:: hallmark.downloader
   :members:

.. automodule:: hallmark.paraframe
   :members:

Building a repository
---------------------

Build a repository and choose filename formats interactively::

   hallmark build ./repositories EHTC_2018L1_Dec2024

Load formats and remotes from an existing configuration::

   hallmark build ./repositories EHTC_2018L1_Dec2024 \
       --config-file ./existing/config.yml

Provide filename formats directly::

   hallmark build ./repositories EHTC_EXAMPLE \
       --fmt "images/{source}_{date}.fits=data" \
       --fmt "README.{format}=readme"

Provide a custom remote or remotes::

   hallmark build ./repositories EHTC_EXAMPLE \
       --remote "origin=https://data.example.org/EHTC_EXAMPLE/" \
       --remote "backup=https://backup.example.org/EHTC_EXAMPLE/"

The generated repository is named ``DATASET_NAME.hm``. The ``--fmt`` option
may be repeated, but it cannot be combined with ``--config-file``.

Downloading remote data
-----------------------

Download specific remote-relative paths::

   hallmark download README.md data/example.fits

Download everything represented by a configured TSV::

   hallmark download --tsv data.tsv

Preview a complete repository download::

   hallmark download --all --dry-run

Large selections require confirmation unless ``--yes`` is supplied.