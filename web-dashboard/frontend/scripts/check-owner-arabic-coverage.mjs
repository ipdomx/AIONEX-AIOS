import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const sourceRoot = path.resolve("src");
const scanRoots = [
  "app/owner",
  "app/settings",
  "components/layout",
  "components/accessibility",
  "components/owner",
].map((value) => path.join(sourceRoot, value));
const translatedSource = path.join(sourceRoot, "lib/interface-translations.ts");
const displayPropertyNames = new Set([
  "label",
  "title",
  "description",
  "subtitle",
  "message",
  "copy",
  "placeholder",
  "help",
  "note",
  "heading",
  "eyebrow",
  "empty",
  "name",
]);
const technicalDisplayTokens = new Set([
  "AIONEX AIOS",
  "ISO 27001",
  "SOC 2",
  "KB ·",
  "⇧⌘K",
]);
const classTokenPrefixes = [
  "bg-",
  "text-",
  "border-",
  "border ",
  "flex",
  "grid",
  "rounded",
  "glass",
  "inline",
  "fixed",
  "relative",
  "absolute",
  "hidden",
  "block",
  "space-",
  "mt-",
  "mb-",
  "ml-",
  "mr-",
  "ms-",
  "me-",
  "px-",
  "py-",
  "p-",
  "w-",
  "h-",
  "max-",
  "min-",
  "sm:",
  "md:",
  "lg:",
  "xl:",
  "2xl:",
  "ring-",
  "cursor-",
  "transition",
  "hover:",
  "disabled:",
  "left-",
  "right-",
];

function normalizeDisplayText(value) {
  return value.replaceAll("&amp;", "&").replace(/\s+/g, " ").trim();
}

function isDisplayText(value) {
  return (
    value.length >= 2 &&
    value.length <= 500 &&
    /[A-Za-z]/.test(value) &&
    !/^[-\w.:/@]+$/.test(value) &&
    !value.includes("className") &&
    !value.includes("${") &&
    !value.includes("=>") &&
    !classTokenPrefixes.some((prefix) => value.startsWith(prefix))
  );
}

function sourceFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(target);
    return /\.tsx?$/.test(entry.name) ? [target] : [];
  });
}

function collectVisibleStrings() {
  const values = new Map();
  const add = (raw, file, node, sourceFile) => {
    const value = normalizeDisplayText(raw);
    if (!isDisplayText(value)) return;
    const line =
      sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line +
      1;
    const locations = values.get(value) ?? [];
    locations.push(`${path.relative(sourceRoot, file)}:${line}`);
    values.set(value, locations);
  };

  for (const file of scanRoots.flatMap(sourceFiles)) {
    const source = fs.readFileSync(file, "utf8");
    const sourceFile = ts.createSourceFile(
      file,
      source,
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TSX,
    );
    const visit = (node) => {
      if (ts.isJsxText(node))
        add(node.getText(sourceFile), file, node, sourceFile);
      if (
        ts.isJsxAttribute(node) &&
        node.initializer &&
        ts.isStringLiteral(node.initializer) &&
        ["placeholder", "title", "aria-label"].includes(node.name.text)
      ) {
        add(node.initializer.text, file, node, sourceFile);
      }
      if (ts.isPropertyAssignment(node)) {
        const name =
          ts.isIdentifier(node.name) || ts.isStringLiteral(node.name)
            ? node.name.text
            : "";
        if (
          displayPropertyNames.has(name) &&
          (ts.isStringLiteral(node.initializer) ||
            ts.isNoSubstitutionTemplateLiteral(node.initializer))
        ) {
          add(node.initializer.text, file, node, sourceFile);
        }
      }
      if (ts.isCallExpression(node)) {
        const callName = ts.isIdentifier(node.expression)
          ? node.expression.text
          : ts.isPropertyAccessExpression(node.expression)
            ? node.expression.name.text
            : "";
        if (["setMessage", "confirm", "alert"].includes(callName)) {
          for (const argument of node.arguments) {
            if (
              ts.isStringLiteral(argument) ||
              ts.isNoSubstitutionTemplateLiteral(argument)
            ) {
              add(argument.text, file, argument, sourceFile);
            }
          }
        }
      }
      if (ts.isConditionalExpression(node)) {
        for (const branch of [node.whenTrue, node.whenFalse]) {
          if (
            ts.isStringLiteral(branch) ||
            ts.isNoSubstitutionTemplateLiteral(branch)
          ) {
            add(branch.text, file, branch, sourceFile);
          }
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sourceFile);
  }
  return values;
}

function arabicCatalogueKeys() {
  const source = fs.readFileSync(translatedSource, "utf8");
  const sourceFile = ts.createSourceFile(
    translatedSource,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS,
  );
  const keys = new Set();
  const visit = (node) => {
    if (
      ts.isVariableDeclaration(node) &&
      node.name.getText(sourceFile) === "AR" &&
      node.initializer &&
      ts.isObjectLiteralExpression(node.initializer)
    ) {
      for (const property of node.initializer.properties) {
        if (
          ts.isPropertyAssignment(property) &&
          (ts.isIdentifier(property.name) || ts.isStringLiteral(property.name))
        ) {
          keys.add(normalizeDisplayText(property.name.text));
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return keys;
}

const visible = collectVisibleStrings();
const catalogue = arabicCatalogueKeys();
const missing = [...visible.entries()].filter(
  ([value]) => !catalogue.has(value) && !technicalDisplayTokens.has(value),
);

if (missing.length) {
  console.error("Owner Arabic coverage is incomplete:");
  for (const [value, locations] of missing) {
    console.error(`- ${value} (${locations.slice(0, 3).join(", ")})`);
  }
  process.exit(1);
}

console.log(
  `Owner Arabic coverage passed: ${visible.size - technicalDisplayTokens.size} translatable UI strings; ${technicalDisplayTokens.size} approved technical tokens.`,
);
