import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const runtime='C:/Users/aicam/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const modules=runtime+'/node/node_modules';
const require=createRequire(import.meta.url);
const {FontLibrary}=require(modules+'/@oai/artifact-tool/node_modules/skia-canvas');
FontLibrary.use('Malgun Gothic',['C:/Windows/Fonts/malgun.ttf','C:/Windows/Fonts/malgunbd.ttf']);
FontLibrary.use('Arial Black','C:/Windows/Fonts/ariblk.ttf');
const {PresentationFile,FileBlob}=await import(pathToFileURL(modules+'/@oai/artifact-tool/dist/artifact_tool.mjs').href);
const p=await PresentationFile.importPptx(await FileBlob.load('output/energy-planner-portfolio.pptx'));
const out='analysis/portfolio_build_20261106/final-renders';
await fs.mkdir(out,{recursive:true});
for(let i=0;i<p.slides.items.length;i++){
  const blob=await p.export({slide:p.slides.items[i],format:'png',scale:1});
  await fs.writeFile(path.join(out,`slide-${i+1}.png`),new Uint8Array(await blob.arrayBuffer()));
}
console.log(JSON.stringify({importedSlides:p.slides.items.length,renderedSlides:p.slides.items.length,directory:out}));
