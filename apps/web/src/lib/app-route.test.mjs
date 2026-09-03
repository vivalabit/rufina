import assert from "node:assert/strict";
import test from "node:test";

import {
  findWorkspaceApplication,
  getHashForView,
  getRouteFromHash,
} from "./app-route.ts";

test("recognizes the legacy application workspace hash", () => {
  assert.deepEqual(getRouteFromHash("#application-workspace"), {
    view: "ApplicationWorkspace",
  });
});

test("adds an encoded application ID to the workspace hash", () => {
  assert.equal(
    getHashForView("ApplicationWorkspace", "application/acme role"),
    "#application-workspace/application%2Facme%20role",
  );
});

test("restores the application ID from the workspace hash", () => {
  assert.deepEqual(
    getRouteFromHash("#application-workspace/application%2Facme%20role"),
    {
      view: "ApplicationWorkspace",
      applicationId: "application/acme role",
    },
  );
});

test("stores the selected job in the jobs hash", () => {
  assert.equal(
    getHashForView("Jobs", "job/acme role"),
    "#jobs/job%2Facme%20role",
  );
  assert.deepEqual(getRouteFromHash("#jobs/job%2Facme%20role"), {
    view: "Jobs",
    jobId: "job/acme role",
  });
});

test("stores the selected application in the applications hash", () => {
  assert.equal(
    getHashForView("Applications", "application/acme role"),
    "#applications/application%2Facme%20role",
  );
  assert.deepEqual(
    getRouteFromHash("#applications/application%2Facme%20role"),
    {
      view: "Applications",
      applicationId: "application/acme role",
    },
  );
});

test("keeps existing view hashes working", () => {
  assert.deepEqual(getRouteFromHash("#applications"), { view: "Applications" });
  assert.equal(getHashForView("Applications"), "#applications");
  assert.deepEqual(getRouteFromHash("#unknown"), { view: "Dashboard" });
});

test("requires an application ID before resolving a workspace application", () => {
  const applications = [{ id: "first" }, { id: "second" }];

  assert.equal(findWorkspaceApplication(applications, undefined), null);
  assert.equal(findWorkspaceApplication(applications, null), null);
  assert.equal(findWorkspaceApplication(applications, "missing"), null);
  assert.equal(
    findWorkspaceApplication(applications, "second"),
    applications[1],
  );
});
