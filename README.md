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
