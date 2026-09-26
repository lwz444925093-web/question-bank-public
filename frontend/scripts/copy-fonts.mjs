import {cpSync,mkdirSync} from 'node:fs';mkdirSync('dist/fonts',{recursive:true});cpSync('node_modules/mathlive/fonts','dist/fonts',{recursive:true});
