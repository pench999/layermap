export type Edit={from:number;to:number;insert:string};
export type UndoEdit={edits:Edit[];conflict:boolean};
export const normalized=(s:string)=>s.replace(/\r\n|\r/g,'\n');
export const newline=(s:string)=>s.includes('\r\n')?'\r\n':s.includes('\r')&&!s.includes('\n')?'\r':'\n';
export const editorOffset=(s:string,p:number)=>normalized(s.slice(0,p)).length;
export function rawOffset(s:string,p:number){let i=0,n=0;while(i<s.length&&n<p){i+=s[i]==='\r'&&s[i+1]==='\n'?2:1;n++;}return i;}
export function edited(s:string,edits:Edit[]){for(const e of [...edits].reverse())s=s.slice(0,e.from)+e.insert+s.slice(e.to);return s;}
export function inverse(s:string,edits:Edit[]):UndoEdit{let delta=0;return {conflict:false,edits:edits.map(e=>{const from=e.from+delta;delta+=e.insert.length-(e.to-e.from);return {from,to:from+e.insert.length,insert:s.slice(e.from,e.to)};})};}
export function trackUndo(undo:UndoEdit,changes:Edit[]):UndoEdit{
  let conflict=undo.conflict;
  const edits=undo.edits.map(e=>{let shift=0;
    for(const c of changes){if(c.from===c.to?c.from>e.from&&c.from<e.to:c.from<e.to&&c.to>e.from)conflict=true;if(c.to<=e.from)shift+=c.insert.length-(c.to-c.from);}
    return {...e,from:e.from+shift,to:e.to+shift};
  });return {edits,conflict};
}
