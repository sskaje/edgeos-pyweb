/**
 * login.js
 * Copyright 2012 Ubiquiti Networks, Inc. All rights reserved.
 */
$(function() {
	var app = window.app || {};
	window.app = app;
	
	//hides the loading bar and renders and shows the login page
	app.initialize = function(debug) {
		$('#LoginButton').button();
		
		$('#TermsOfUse').bind('change', function() {
			var $this = $(this);
			if ($this.is(':checked')) {
				$('#LoginButton').button('option', 'disabled', false);
			} else {
				$('#LoginButton').button('option', 'disabled', true);
			}
		}).trigger('change');
		
		$('.unrendered').css('visibility', 'visible');
		$('#Username').focus();
	};
});
