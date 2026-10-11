// Ground truth for TypeScript: files that reference each target, via the TS language service.
// usage: node ts_refs.js <repoRoot> <targets.json>   targets: [{file,line,name}]  -> JSON {key: [files]}
const ts = require("typescript"), fs = require("fs"), path = require("path");
const [root, targetsPath] = process.argv.slice(2);
const cfg = ts.getParsedCommandLineOfConfigFile(path.join(root, "tsconfig.json"), {}, {
  ...ts.sys, onUnRecoverableConfigFileDiagnostic: () => {} });
const files = cfg.fileNames.filter(f => !f.includes("node_modules"));
const host = {
  getScriptFileNames: () => files, getScriptVersion: () => "1",
  getScriptSnapshot: f => fs.existsSync(f) ? ts.ScriptSnapshot.fromString(fs.readFileSync(f, "utf8")) : undefined,
  getCurrentDirectory: () => root, getCompilationSettings: () => cfg.options,
  getDefaultLibFileName: ts.getDefaultLibFilePath, fileExists: ts.sys.fileExists,
  readFile: ts.sys.readFile, readDirectory: ts.sys.readDirectory,
};
const ls = ts.createLanguageService(host);
const out = {};
for (const t of JSON.parse(fs.readFileSync(targetsPath, "utf8"))) {
  const abs = path.join(root, t.file);
  const text = fs.readFileSync(abs, "utf8").split("\n")[t.line - 1] || "";
  const col = text.indexOf(t.name);
  if (col < 0) { out[t.key] = null; continue; }
  const pos = ts.getPositionOfLineAndCharacter(ls.getProgram().getSourceFile(abs) || ts.createSourceFile(abs, text, 99), t.line - 1, col);
  const refs = ls.getReferencesAtPosition(abs, pos) || [];
  out[t.key] = [...new Set(refs.map(r => path.relative(root, r.fileName)))];
}
out.__scope = files.map(f => path.relative(root, f)); // files the compiler actually saw
console.log(JSON.stringify(out));
