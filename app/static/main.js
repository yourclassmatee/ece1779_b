(function(){
    // do some stuff
    //console.log("lallal");
     $.ajax({
            url: $SCRIPT_ROOT + '/get_cpu_ajax',
            type: 'GET',
            success: function(response) {
                console.log(response)
                var obj  = JSON.parse(response)
                //console.log(obj);
                for (id in obj){
                    //.log(id);
                    //console.log(obj[id])
                    document.getElementById(id).innerHTML = obj[id]
                }
            },
            error: function(error) {
                console.log(error);
            }
        });
    setTimeout(arguments.callee, 30000);
})();