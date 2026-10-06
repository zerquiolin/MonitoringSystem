export type ServiceStatus = 'UP'|'DOWN'|'DEGRADED'|'UNKNOWN'|'MAINTENANCE'|'DRAINING';
export interface Identity {project:string;service:string;environment:string;instance?:string}
export interface ReliabilityReport extends Identity {
 from:number;to:number;windowSeconds:number;uptimeSeconds:number;downtimeSeconds:number;
 degradedSeconds:number;unknownSeconds:number;maintenanceSeconds:number;excludedMaintenanceSeconds:number;
 availability:number|null;coverage:number|null;target:number;errorBudgetConsumed:number|null;
 errorBudgetSeconds:number;errorBudgetRemainingSeconds:number|null;incidentCount:number;activeIncidents:number;
 mttrSeconds:number|null;meanAcknowledgmentSeconds:number|null;compliance:'MET'|'MISSED'|'INSUFFICIENT_DATA';partialWindow:boolean;definition:string;
}
export interface Incident extends Identity {id:string;status:'OPEN'|'RESOLVED'|'RETIRED';reason:string;opened:number;first_failure:number;previous_success:number|null;last_failure:number;recovered:number|null;acknowledged:number|null;durationSeconds:number;outageLowerBoundSeconds:number;outageUpperBoundSeconds:number}
export interface ReportQuery {project?:string;service?:string;environment?:string;start?:number;end?:number;limit?:number;format?:'json'|'csv'}
