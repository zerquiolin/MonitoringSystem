export function resourceAttributes(r:{project:string;service:string;environment:string;instance:string}) {
 return {'service.namespace':r.project,'service.name':r.service,'deployment.environment.name':r.environment,'service.instance.id':r.instance,project:r.project,service:r.service,environment:r.environment,instance:r.instance};
}
