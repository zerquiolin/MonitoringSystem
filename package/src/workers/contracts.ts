export interface WorkerResource {project:string;service:string;environment:string;instance:string;}
export interface Heartbeat {resource:WorkerResource;bootId:string;sequence:number;ready:boolean;progress:number;activeJobs:number;timestamp:number;}
export interface JobEvent {resource:WorkerResource;runId:string;bootId:string;state:'started'|'completed'|'failed';name:string;timestamp:number;}
