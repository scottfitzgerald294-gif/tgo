import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const sourcePath = '/workspace/src/stores/providerModelTypes.ts';
const source = fs.readFileSync(sourcePath, 'utf8');

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;

const module = { exports: {} };
vm.runInNewContext(
  `(function (exports, module) { ${compiled} })(module.exports, module);`,
  { module }
);

const { mergeProviderModels } = module.exports;

const result = mergeProviderModels(
  [{ model_id: 'nomic-embed-text', model_type: 'embedding' }],
  [{ model_id: 'qwen3:8b', model_type: 'chat' }]
);

assert.deepEqual(
  JSON.parse(JSON.stringify(result)),
  [
    { model_id: 'nomic-embed-text', model_type: 'embedding' },
    { model_id: 'qwen3:8b', model_type: 'chat' },
  ]
);

console.log('PASS: existing embedding model type is preserved');
