// validate_runtime_context.js
// Checks that the Figma plugin API is reachable and variables API is available.
// Returns: { ok: boolean, checks: [{ name, passed, detail }] }

const checks = [];

function check(name, fn) {
  try {
    const detail = fn();
    checks.push({ name, passed: true, detail: detail ?? null });
  } catch (e) {
    checks.push({ name, passed: false, detail: String(e.message) });
  }
}

check("figma_api", () => {
  if (typeof figma === "undefined") throw new Error("figma global not found");
  return "ok";
});

check("variables_api", () => {
  if (typeof figma.variables === "undefined") throw new Error("figma.variables not available");
  if (typeof figma.variables.getLocalVariableCollections !== "function")
    throw new Error("getLocalVariableCollections not a function");
  return "ok";
});

check("current_page", () => {
  const name = figma.currentPage.name;
  if (!name) throw new Error("currentPage.name is empty");
  return name;
});

check("create_variable_api", () => {
  if (typeof figma.variables.createVariableCollection !== "function")
    throw new Error("createVariableCollection not a function");
  if (typeof figma.variables.createVariable !== "function")
    throw new Error("createVariable not a function");
  return "ok";
});

const allPassed = checks.every((c) => c.passed);
return { ok: allPassed, checks };
