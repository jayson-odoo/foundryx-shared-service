# 71 - AutoCount project registration routes (Shared Service half, slice 1)

Lane: AUTOCOUNT-PROJREG-SPO-SS. Partner CRM lane: AUTOCOUNT-PROJREG-SPO (sorento-crm plan
`documentation/plans/autocount/PLAN-autocount-projreg-spo-21nov.md`, Part A = the contract).

Status: Plan (work in progress - this file is filled in as the slice is built).

## Scope

Behind a per-company switch, OFF by default:

- `POST  /api/v1/autocount/project-registrations` -> wrapper `POST /NewProjectReg`
- `PATCH /api/v1/autocount/project-registrations/{projNo}` -> wrapper `PUT /EditProjectRegbyProjNo` (whole record)
- `GET   /api/v1/autocount/project-registrations/{projNo}?companyCode=` -> wrapper `GET /ProjectRegbyProjNo?ProjNo=`
- `GET   /api/v1/autocount/project-registrations?companyCode=&date=yyyymmdd` -> wrapper `GET /ProjectRegbyDate?Date=`
