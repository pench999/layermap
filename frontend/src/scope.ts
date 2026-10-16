import type {Endpoint} from './trace';
export type Limits={yaml_bytes:number;devices:number;elements:number;view_devices:number;view_rows:number;view_connections:number;view_elements:number;view_groups:number;svg_bytes:number};
export const defaultLimits:Limits={yaml_bytes:2097152,devices:256,elements:10000,view_devices:24,view_rows:200,view_connections:400,view_elements:500,view_groups:80,svg_bytes:4194304};
export type Scope={site:string|null;group:string|null;device_ids:string[];trace_root:Endpoint|null};
export const emptyScope=():Scope=>({site:null,group:null,device_ids:[],trace_root:null});
export type Result={svg:string;devices:{id:string;name:string;site:string;groups:string[]}[];visible_devices:string[];counts:{devices:number;links:number;vlans:number};limits:Limits;catalog:{sites:string[];groups:string[];focus_options:(Endpoint&{label:string})[]};display:{status:'ready'|'too_large'|'empty';message:string;filtered:boolean;counts:{devices:number;rows:number;connections:number;elements:number;groups:number};boundary_links:{noun:string;total:number;items:{id:string;local:string;remote:string;remote_device:string|null;kind:'wired'|'wifi';status:'confirmed'|'port_unknown'|'peer_unknown';ssid:string|null;observed_at:string|null}[];has_more:boolean}}};
export const sizeLabel=(bytes:number)=>bytes>=1048576?(bytes/1048576)+' MiB':(bytes/1024)+' KiB';
