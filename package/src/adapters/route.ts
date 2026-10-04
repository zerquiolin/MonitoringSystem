/** Express does not expose dynamic mount templates at response completion.
 * Never turn its resolved baseUrl into a metric label. Use middleware(fullTemplate)
 * on nested routes where the full mount template is not available.
 */
export function expressRoute(req:any):string {
 return typeof req.route?.path==='string'?req.route.path:'unmatched';
}
