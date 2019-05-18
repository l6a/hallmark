# Hallmark

> Reproducibility is the hallmark of the scientific method.

Modern science has become so complex that many science projects rely
on multiple software packages to work in unison, resulting networks of
data products along the analyses.
Versioning and managing these data products are essential in making
modern data- and computation-intensive science reproducible.

Motivated by the Event Horizon Telescope (EHT)'s data calibration
pipelines, `hallmark` is a lightweight tool designed to version
control and manage data products in a complex workflow.
It provides a simple abstraction and a uniform Application Programming
Interface (API) on top of different backend technologies such as Git
Large File Storage (LFS), Globus, iRODS, etc.
By using `hallmark` with other tools such as `yukon` and `banyan` in
Project Laniakea, researchers can utilize computing infrastructures in
a global scale to accelerate their science.

## Usage

From a user point of view, the frontends of `hallmark` provide simple
and consistent methods to access data products.

Suppose that we need to access a repository containing data in EHT's
first science release, we start by registering the repository locally.
In bash, this is

    bash$ alias hm='hallmark'
    bash$ hm mount https://eventhorizontelescope.org/data/2017April_SR1 SR1
    Hallmark: mounting remote repository "https://eventhorizontelescope.org/data/2017April_SR1" on local file system "SR1"...  DONE.
    bash$ ls
    Desktop   Documents ...       SR1

In python, this is

    >>> import hallmark as hm
    >>> sr1 = hm.mount("https://https://eventhorizontelescope.org/data/2017April_SR1")

The mount points now acts like standard directory that one can easily
inspect by standard Unix utilities and python functions.  E.g.,

    bash$ find SR1
    SR1
    SR1/EHTC_FirstM87Results_Apr2019_txt.tgz
    ...
    SR1/INVENTORY.txt
    SR1/LICENSE.txt
    SR1/README.md
    SR1/run.sh

or in python

    >>> sr1
    {'EHTC_FirstM87Results_Apr2019_txt.tgz': <data object>, ..., 'run.sh': <data object>}
